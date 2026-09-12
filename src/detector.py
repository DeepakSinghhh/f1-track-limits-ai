"""Demo CV pipeline: YOLO vehicle detection -> a fixed screen-space zone
crossing -> ExcursionEvent (hysteresis + duration gate) -> the real Tier 2
rule engine. Never issues a penalty and never auto-increments a strike —
see app.py for the steward-confirmation flow that is the only path to
either.
"""
import cv2
import numpy as np
from ultralytics import YOLO

from src.config import EventConfig, load_event_config
from src.geofence import ZoneCrossingTracker
from src.rules.engine import RuleEngine
from src.schemas import Finding, Verdict

#: COCO class ids this pipeline treats as vehicles: car, motorcycle, bus, truck.
VEHICLE_CLASS_IDS = {2, 3, 5, 7}


class TrackLimitDetector:
    def __init__(
        self,
        fps: float,
        config: EventConfig | str = "config/events/demo_clip.yaml",
        conf_threshold: float = 0.5,
        min_duration_s: float | None = None,
    ):
        self.model = YOLO("yolov8n.pt")
        self.config = config if isinstance(config, EventConfig) else load_event_config(config)
        self.rule_engine = RuleEngine(self.config)
        self.tracker = ZoneCrossingTracker(
            fps=fps,
            min_duration_s=min_duration_s if min_duration_s is not None else self.config.min_event_duration_s,
        )
        self.conf_threshold = conf_threshold
        self.demo_zone = None

    def process_frame(self, frame, frame_id: int) -> tuple[np.ndarray, list[tuple[Finding, Verdict]]]:
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

        results = self.model(frame, verbose=False)[0]

        any_violating = False
        for box in results.boxes:
            if int(box.cls) not in VEHICLE_CLASS_IDS:
                continue
            if float(box.conf) < self.conf_threshold:
                continue

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            u, v = int((x1 + x2) / 2), y2  # bottom-centre reference point — not a contact patch

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

        findings: list[tuple[Finding, Verdict]] = []
        event = self.tracker.update(any_violating, frame_id)
        if event is not None:
            findings.append(self.rule_engine.evaluate(event))

        return frame, findings

    def finalize(self, frame_id: int) -> list[tuple[Finding, Verdict]]:
        """Call once after the frame loop ends, so a still-open excursion
        at the end of the clip is evaluated rather than silently dropped.
        """
        event = self.tracker.close(frame_id)
        if event is None:
            return []
        return [self.rule_engine.evaluate(event)]
