"""Per-clip camera calibration (Section 5.3): image (pixel) <-> world
(metres) via a homography fit from point correspondences the operator
actually supplies.

The previous version of this file hardcoded one clip's four points as a
fixed homography -- silently wrong for any other video, which is worse
than not calibrating at all. Section 5.3 describes an interactive "click
4+ known track points" tool; this module is the calibration math that
tool (app.py's calibration form, for now -- a numeric form rather than a
click-to-pick canvas, see its docstring) drives. There is no default
calibration here on purpose: a clip is either explicitly calibrated by
whoever is running it, or the pipeline honestly falls back to the
uncalibrated demo-zone behaviour, never a guess.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


class CalibrationError(ValueError):
    """Point correspondences can't produce a usable homography."""


@dataclass(frozen=True)
class CameraCalibration:
    homography: np.ndarray          # 3x3: image (u, v) -> world (x, y), metres
    inverse_homography: np.ndarray  # 3x3: world (x, y) -> image (u, v)
    reprojection_error_px: float    # mean error of the fitted points, in pixels

    def pixel_to_world(self, u: float, v: float) -> tuple[float, float]:
        return _apply(self.homography, u, v)

    def world_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        return _apply(self.inverse_homography, x, y)


def _apply(h: np.ndarray, a: float, b: float) -> tuple[float, float]:
    point = h @ np.array([a, b, 1.0])
    if point[2] == 0:
        raise CalibrationError("degenerate homography (zero denominator on projection)")
    return float(point[0] / point[2]), float(point[1] / point[2])


def calibrate(
    image_points: list[tuple[float, float]],
    world_points: list[tuple[float, float]],
) -> CameraCalibration:
    """Fit a homography from >=4 point correspondences (Section 5.3:
    "operator clicks 4+ known track points"). Raises CalibrationError on
    too few points or a degenerate fit (e.g. collinear points) -- never
    returns a calibration that silently doesn't work.
    """
    if len(image_points) != len(world_points):
        raise CalibrationError("image_points and world_points must be the same length")
    if len(image_points) < 4:
        raise CalibrationError(f"need at least 4 point correspondences, got {len(image_points)}")

    src = np.array(image_points, dtype=np.float64)
    dst = np.array(world_points, dtype=np.float64)

    homography, _ = cv2.findHomography(src, dst)
    if homography is None:
        raise CalibrationError("cv2.findHomography could not fit a solution -- check for collinear points")

    try:
        inverse = np.linalg.inv(homography)
    except np.linalg.LinAlgError as exc:
        raise CalibrationError("fitted homography is singular (not invertible)") from exc

    # Reprojection error: round-trip each supplied world point back through
    # the inverse homography and compare to the pixel it came from. Reported
    # rather than assumed good -- this is what evidence_quality (trust/) will
    # eventually read to judge this clip's geometry, once wired in.
    errors = []
    for (u, v), (x, y) in zip(image_points, world_points):
        reprojected_u, reprojected_v = _apply(inverse, x, y)
        errors.append(float(np.hypot(reprojected_u - u, reprojected_v - v)))

    return CameraCalibration(
        homography=homography,
        inverse_homography=inverse,
        reprojection_error_px=float(np.mean(errors)),
    )
