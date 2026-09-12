"""Demo CV pipeline: YOLO vehicle detection -> ExcursionEvent -> the real
Tier 2 rule engine. Never issues a penalty and never auto-increments a
strike -- see app.py for the steward-confirmation flow that is the only
path to either.

Two modes, chosen by whether a calibration is supplied:

- Uncalibrated (default): a single reference pixel per vehicle tested
  against a fixed on-screen zone (src.geofence.ZoneCrossingTracker).
  wheels_off_peak is always None -- honestly, since there is no per-wheel
  or metric data -- and the rule engine correctly reports
  INSUFFICIENT_EVIDENCE for every candidate.
- Calibrated: with a real homography (src.calibration) and a track model
  for this clip's visible span (src.track.build.build_straight_segment_track),
  every frame's best detection becomes a real CarState with real per-wheel
  positions (src.kinematics), fed straight into the actual Tier 1
  (src.events.localise) and Tier 2 pipeline -- the same modules the rest
  of this project uses, not a parallel implementation. This is what
  produces genuine VIOLATION findings instead of permanent abstention.
"""
from __future__ import annotations

import cv2
import numpy as np

from src.calibration import CameraCalibration
from src.config import EventConfig, load_event_config
from src.events.localise import localise_events
from src.geofence import ZoneCrossingTracker
from src.kinematics import wheel_world_positions
from src.render.overlay import draw_boundary_overlay, draw_contact_points, project_boundary_edge, wheel_margins
from src.rules.engine import RuleEngine
from src.schemas import CarState, ExcursionEvent, Finding, Verdict
from src.track.boundary import Boundary
from src.track.frame import TrackFrame

#: COCO class ids this pipeline treats as vehicles: car, motorcycle, bus, truck.
VEHICLE_CLASS_IDS = {2, 3, 5, 7}

#: How much of the calibrated track either side of the current car to draw
#: the boundary overlay for -- cosmetic only, has no effect on findings.
DRAW_S_WINDOW_M = 30.0


class TrackLimitDetector:
    def __init__(
        self,
        fps: float,
        config: EventConfig | str = "config/events/demo_clip.yaml",
        conf_threshold: float = 0.5,
        min_duration_s: float | None = None,
        calibration: CameraCalibration | None = None,
        track_frame: TrackFrame | None = None,
        boundary: Boundary | None = None,
        heading_rad: float | None = None,
        corner: int = 0,
        car_number: int = 0,
    ):
        if calibration is not None and (track_frame is None or boundary is None or heading_rad is None):
            raise ValueError("track_frame, boundary and heading_rad are all required when calibration is given")

        self._model = None  # lazy: only touches ultralytics/torch once process_frame actually runs
        self.config = config if isinstance(config, EventConfig) else load_event_config(config)
        self.rule_engine = RuleEngine(self.config)
        self.conf_threshold = conf_threshold
        self.fps = fps

        self.calibration = calibration
        self.track_frame = track_frame
        self.boundary = boundary
        self.heading_rad = heading_rad
        self.corner = corner
        self.car_number = car_number
        self._states: list[CarState] = []

        self.demo_zone = None
        self.tracker = None
        if calibration is None:
            self.tracker = ZoneCrossingTracker(
                fps=fps,
                min_duration_s=min_duration_s if min_duration_s is not None else self.config.min_event_duration_s,
            )

    @property
    def model(self):
        if self._model is None:
            from ultralytics import YOLO  # deferred: geometry-only use (tests, calibration) needs no YOLO/torch at all

            self._model = YOLO("yolov8n.pt")
        return self._model

    def process_frame(
        self, frame, frame_id: int
    ) -> tuple[np.ndarray, list[tuple[ExcursionEvent, Finding, Verdict]]]:
        results = self.model(frame, verbose=False)[0]

        if self.calibration is not None:
            return self._process_frame_calibrated(frame, frame_id, results)
        return self._process_frame_uncalibrated(frame, frame_id, results)

    # ---- calibrated path ----

    def _best_detection(self, results):
        best_box, best_conf = None, -1.0
        for box in results.boxes:
            if int(box.cls) not in VEHICLE_CLASS_IDS:
                continue
            conf = float(box.conf)
            if conf < self.conf_threshold or conf <= best_conf:
                continue
            best_box, best_conf = box, conf
        return best_box

    def car_state_from_reference_point(self, u: float, v: float, frame_id: int) -> CarState:
        """The pure geometry step of the calibrated path: one image
        reference point -> one CarState with real per-wheel data. Exposed
        separately from process_frame so it's testable without running
        YOLO.
        """
        car_x, car_y = self.calibration.pixel_to_world(u, v)
        car_s, car_d = self.track_frame.to_frenet(car_x, car_y)

        wheels = wheel_world_positions((car_x, car_y), self.heading_rad)
        wheel_d = tuple(self.track_frame.to_frenet(wx, wy)[1] for wx, wy in wheels)

        return CarState(
            car_number=self.car_number,
            session_time=frame_id / self.fps,
            s=car_s,
            d=car_d,
            heading=self.heading_rad,
            speed=0.0,      # not estimated -- no multi-frame tracking here; unused by localise_events
            yaw_rate=0.0,   # not estimated; unused by localise_events
            wheel_d=wheel_d,
            wheel_sigma=None,  # unknown -- events.localise falls back to its own default sigma
            source="vision",
            reproj_error_px=self.calibration.reprojection_error_px,
            occlusion_frac=0.0,
            n_sensors=1,
        )

    def _process_frame_calibrated(self, frame, frame_id, results):
        box = self._best_detection(results)

        if box is not None:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            u, v = (x1 + x2) / 2, y2
            state = self.car_state_from_reference_point(u, v, frame_id)
            self._states.append(state)

            wheels_xy = wheel_world_positions(self.calibration.pixel_to_world(u, v), self.heading_rad)
            margins = wheel_margins(self.track_frame, self.boundary, wheels_xy)
            outside_flags = [m > 0 for m in margins]
            points_uv = np.array([self.calibration.world_to_pixel(x, y) for x, y in wheels_xy])

            color = (0, 0, 255) if any(outside_flags) else (0, 255, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            draw_contact_points(frame, points_uv, outside_flags)

            left_edge = project_boundary_edge(
                self.track_frame, self.boundary, state.s - DRAW_S_WINDOW_M, state.s + DRAW_S_WINDOW_M,
                "left", self.calibration.inverse_homography,
            )
            right_edge = project_boundary_edge(
                self.track_frame, self.boundary, state.s - DRAW_S_WINDOW_M, state.s + DRAW_S_WINDOW_M,
                "right", self.calibration.inverse_homography,
            )
            draw_boundary_overlay(frame, left_edge, right_edge)

        cv2.putText(
            frame, "CALIBRATED (real boundary, per-wheel)", (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
        )

        return frame, []  # findings are computed once, in finalize() -- localise_events needs the full sequence

    # ---- uncalibrated path (unchanged behaviour) ----

    def _process_frame_uncalibrated(self, frame, frame_id, results):
        h, w = frame.shape[:2]

        if self.demo_zone is None:
            self.demo_zone = np.array([[w // 2, h // 2], [w, h // 2], [w, h], [w // 3 + 50, h]])

        overlay = frame.copy()
        cv2.fillPoly(overlay, [self.demo_zone], (0, 0, 255))
        cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)
        cv2.putText(
            frame,
            "DEMO ZONE (illustrative, not a calibrated boundary)",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
        )
        cv2.polylines(frame, [self.demo_zone], isClosed=True, color=(0, 0, 255), thickness=2)

        any_violating = False
        for box in results.boxes:
            if int(box.cls) not in VEHICLE_CLASS_IDS:
                continue
            if float(box.conf) < self.conf_threshold:
                continue

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            u, v = int((x1 + x2) / 2), y2  # bottom-centre reference point -- not a contact patch

            violating = cv2.pointPolygonTest(self.demo_zone, (u, v), False) >= 0
            any_violating = any_violating or violating

            color = (0, 0, 255) if violating else (0, 255, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.circle(frame, (u, v), 6, color, -1)
            cv2.putText(
                frame,
                "OFF ZONE" if violating else "TRACKING",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )

        findings: list[tuple[ExcursionEvent, Finding, Verdict]] = []
        event = self.tracker.update(any_violating, frame_id)
        if event is not None:
            finding, verdict = self.rule_engine.evaluate(event)
            findings.append((event, finding, verdict))

        return frame, findings

    def finalize(self, frame_id: int) -> list[tuple[ExcursionEvent, Finding, Verdict]]:
        """Call once after the frame loop ends."""
        if self.calibration is not None:
            if not self._states:
                return []
            events = localise_events(
                self._states, self.boundary, corner_of=lambda s: self.corner, lap_of=lambda t: 0
            )
            return [(e, *self.rule_engine.evaluate(e)) for e in events]

        event = self.tracker.close(frame_id)
        if event is None:
            return []
        finding, verdict = self.rule_engine.evaluate(event)
        return [(event, finding, verdict)]
