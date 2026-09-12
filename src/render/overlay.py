"""Boundary-overlay replay clip export (Section 5.9).

Named explicitly in the problem statement: "real-time incident flagging
with confidence scores and boundary-overlay replay clips for steward
review." Per clip, this draws:

- the boundary polyline (outer white-line edge), projected world -> image
  via a per-clip homography (world -> image; the inverse of
  src.vision.calibrate's own pixel_to_world)
- contact points, colour-coded inside/outside
- a live readout of the minimum wheel margin in cm, with its uncertainty
- a bird's-eye minimap inset in the same (s, d) plane as track/
- an onset/offset timeline strip

and exports to MP4. The ffmpeg re-encode to a widely-compatible codec is
best-effort: cv2.VideoWriter's own mp4v output is a complete, readable
video on its own (verified — no system ffmpeg needed to read it back), so
a missing ffmpeg binary degrades the output codec, not the pipeline.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

import cv2
import numpy as np

from src.schemas import ExcursionEvent
from src.track.boundary import Boundary
from src.track.frame import TrackFrame
from src.vision.contact import wheel_margins
from src.vision.project import apply_homography, project_boundary_edge

INSIDE_COLOR = (0, 200, 0)      # BGR: green
OUTSIDE_COLOR = (0, 0, 220)     # BGR: red
BOUNDARY_COLOR = (0, 220, 220)  # BGR: yellow
TEXT_COLOR = (255, 255, 255)


@dataclass
class FrameAnnotation:
    """What overlay.py needs for one frame — everything else (margins,
    projections) is derived from this plus the track/boundary model.
    """

    session_time: float
    contact_points_xy: list[tuple[float, float]]  # world-plane coordinates, one per tracked wheel/point


def draw_boundary_overlay(frame: np.ndarray, left_edge_uv: np.ndarray, right_edge_uv: np.ndarray) -> np.ndarray:
    for edge in (left_edge_uv, right_edge_uv):
        pts = edge.astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(frame, [pts], isClosed=False, color=BOUNDARY_COLOR, thickness=2)
    return frame


def draw_contact_points(frame: np.ndarray, points_uv: np.ndarray, outside_flags: list[bool], radius: int = 6) -> np.ndarray:
    for (u, v), outside in zip(points_uv, outside_flags):
        color = OUTSIDE_COLOR if outside else INSIDE_COLOR
        cv2.circle(frame, (int(round(u)), int(round(v))), radius, color, -1)
    return frame


def draw_margin_readout(
    frame: np.ndarray, min_margin_m: float, uncertainty_m: float, origin: tuple[int, int] = (20, 40)
) -> np.ndarray:
    text = f"Min wheel margin: {min_margin_m * 100:+.1f}cm (+/-{uncertainty_m * 100:.1f}cm)"
    cv2.putText(frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.6, TEXT_COLOR, 2)
    return frame


def draw_minimap_inset(
    frame: np.ndarray,
    frame_obj: TrackFrame,
    boundary: Boundary,
    s_center: float,
    s_window_m: float,
    trail_sd: list[tuple[float, float]],
    size: int = 180,
    margin_px: int = 16,
) -> np.ndarray:
    """Bird's-eye (s, d) inset, pasted into the frame's top-right corner."""
    h, w = frame.shape[:2]
    size = min(size, h - 2 * margin_px, w - 2 * margin_px)
    if size <= 0:
        return frame

    canvas = np.full((size, size, 3), 30, dtype=np.uint8)

    s_lo, s_hi = s_center - s_window_m / 2, s_center + s_window_m / 2
    d_span = 12.0  # metres either side of centreline shown in the inset

    def to_canvas(s: float, d: float) -> tuple[int, int]:
        x = int((s - s_lo) / (s_hi - s_lo) * size)
        y = int(size / 2 - (d / d_span) * (size / 2))
        return x, y

    left_pts = np.array([to_canvas(s, boundary.half_width(s)[0]) for s in np.linspace(s_lo, s_hi, 30)], dtype=np.int32)
    right_pts = np.array([to_canvas(s, -boundary.half_width(s)[1]) for s in np.linspace(s_lo, s_hi, 30)], dtype=np.int32)
    cv2.polylines(canvas, [left_pts.reshape(-1, 1, 2)], False, BOUNDARY_COLOR, 1)
    cv2.polylines(canvas, [right_pts.reshape(-1, 1, 2)], False, BOUNDARY_COLOR, 1)

    if trail_sd:
        trail_pts = np.array([to_canvas(s, d) for s, d in trail_sd], dtype=np.int32)
        cv2.polylines(canvas, [trail_pts.reshape(-1, 1, 2)], False, (255, 255, 255), 1)
        cv2.circle(canvas, tuple(trail_pts[-1]), 4, (0, 255, 255), -1)

    x0, y0 = w - size - margin_px, margin_px
    frame[y0 : y0 + size, x0 : x0 + size] = canvas
    cv2.rectangle(frame, (x0, y0), (x0 + size, y0 + size), TEXT_COLOR, 1)
    return frame


def draw_timeline_strip(
    frame: np.ndarray,
    t_onset: float,
    t_max_excursion: float,
    t_reentry: float,
    t_current: float,
    clip_t_start: float,
    clip_t_end: float,
    height: int = 8,
    margin_px: int = 16,
) -> np.ndarray:
    h, w = frame.shape[:2]
    y = h - margin_px
    x0, x1 = margin_px, w - margin_px
    span = max(clip_t_end - clip_t_start, 1e-9)

    def to_x(t: float) -> int:
        frac = min(max((t - clip_t_start) / span, 0.0), 1.0)
        return int(x0 + frac * (x1 - x0))

    cv2.line(frame, (x0, y), (x1, y), (90, 90, 90), height)
    cv2.line(frame, (to_x(t_onset), y), (to_x(t_reentry), y), OUTSIDE_COLOR, height)
    cv2.circle(frame, (to_x(t_max_excursion), y), height, TEXT_COLOR, 1)
    cv2.circle(frame, (to_x(t_current), y), height + 2, (255, 255, 255), -1)
    return frame


def render_incident_clip(
    frames: list[np.ndarray],
    annotations: list[FrameAnnotation],
    event: ExcursionEvent,
    frame_obj: TrackFrame,
    boundary: Boundary,
    homography: np.ndarray,
    output_path: str,
    fps: float,
    s_window_m: float = 40.0,
) -> str:
    """Render one incident's replay clip. Returns the path actually
    written — the raw mp4v path if the ffmpeg re-encode step is
    unavailable or fails, otherwise the re-encoded path.
    """
    if len(frames) != len(annotations):
        raise ValueError("frames and annotations must be the same length")
    if not frames:
        raise ValueError("frames must be non-empty")

    h, w = frames[0].shape[:2]
    clip_t_start = annotations[0].session_time
    clip_t_end = annotations[-1].session_time

    frame_sd = []
    for ann in annotations:
        sd_points = [frame_obj.to_frenet(x, y) for x, y in ann.contact_points_xy]
        mean_s = sum(s for s, _ in sd_points) / len(sd_points)
        mean_d = sum(d for _, d in sd_points) / len(sd_points)
        frame_sd.append((mean_s, mean_d))

    s_center = sum(s for s, _ in frame_sd) / len(frame_sd)
    left_edge = project_boundary_edge(frame_obj, boundary, s_center - s_window_m / 2, s_center + s_window_m / 2, "left", homography)
    right_edge = project_boundary_edge(frame_obj, boundary, s_center - s_window_m / 2, s_center + s_window_m / 2, "right", homography)

    # raw_path must never equal output_path -- otherwise the ffmpeg
    # re-encode step below would read and write the same file.
    stem = output_path[:-4] if output_path.endswith(".mp4") else output_path
    raw_path = f"{stem}_raw.mp4"
    writer = cv2.VideoWriter(raw_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

    trail_sd: list[tuple[float, float]] = []
    for frame, ann, (s, d) in zip(frames, annotations, frame_sd):
        out_frame = frame.copy()
        margins = wheel_margins(frame_obj, boundary, ann.contact_points_xy)
        outside_flags = [m > 0 for m in margins]
        points_uv = apply_homography(homography, np.array(ann.contact_points_xy))

        draw_boundary_overlay(out_frame, left_edge, right_edge)
        draw_contact_points(out_frame, points_uv, outside_flags)
        draw_margin_readout(out_frame, min(margins), event.margin_sigma_m)

        trail_sd.append((s, d))
        draw_minimap_inset(out_frame, frame_obj, boundary, s_center, s_window_m, trail_sd)
        draw_timeline_strip(
            out_frame, event.t_onset, event.t_max_excursion, event.t_reentry, ann.session_time, clip_t_start, clip_t_end
        )

        writer.write(out_frame)
    writer.release()

    return _try_reencode_h264(raw_path, output_path)


def _try_reencode_h264(raw_path: str, output_path: str) -> str:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", raw_path, "-vcodec", "libx264", output_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return output_path
    except (FileNotFoundError, subprocess.CalledProcessError):
        # ffmpeg missing or the re-encode failed: the raw mp4v file is
        # still a complete, readable clip -- degrade the codec, not the
        # pipeline.
        return raw_path
