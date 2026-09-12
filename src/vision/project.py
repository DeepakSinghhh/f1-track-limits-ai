"""World <-> image projection geometry (Section 5.3): sampling the track
boundary in the (s, d) frame and projecting it through a per-clip
homography into pixel space. This is the inverse direction of
vision/calibrate.py's pixel_to_world -- world geometry going out to the
frame, rather than a detection coming in from it -- used both by the live
detector overlay (src/detector.py) and the replay clip export
(src/render/overlay.py).
"""
from __future__ import annotations

import numpy as np

from src.track.boundary import Boundary
from src.track.frame import TrackFrame


def apply_homography(homography: np.ndarray, points_xy: np.ndarray) -> np.ndarray:
    """World (x, y) -> image (u, v) via a 3x3 homography."""
    points_xy = np.atleast_2d(np.asarray(points_xy, dtype=float))
    ones = np.ones((len(points_xy), 1))
    homogeneous = np.hstack([points_xy, ones])  # (N, 3)
    projected = homogeneous @ homography.T  # (N, 3)
    projected = projected[:, :2] / projected[:, 2:3]
    return projected


def project_boundary_edge(
    frame_obj: TrackFrame,
    boundary: Boundary,
    s_start: float,
    s_end: float,
    side: str,
    homography: np.ndarray,
    n_samples: int = 50,
) -> np.ndarray:
    """Sample the outer boundary edge over [s_start, s_end] and project it
    into image space. side: "left" or "right".
    """
    if side not in ("left", "right"):
        raise ValueError("side must be 'left' or 'right'")

    s_values = np.linspace(s_start, s_end, n_samples)
    world_points = []
    for s in s_values:
        w_left, w_right = boundary.half_width(s)
        d = w_left if side == "left" else -w_right
        world_points.append(frame_obj.to_cartesian(s, d))
    return apply_homography(homography, np.array(world_points))
