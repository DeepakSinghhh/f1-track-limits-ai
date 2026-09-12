"""Per-wheel kinematics (Section 5.3): car centre + heading -> four wheel
world positions. "Do not use the box centroid -- the regulation turns on
contact patches and a centroid is indefensible under questioning." This
is the step that turns a single tracked point into the four points
Art. 33.3 actually asks about.
"""
from __future__ import annotations

import numpy as np

#: Typical F1 car dimensions (~3.6m wheelbase, ~2.0m track width), as
#: half-distances from the car centre to each wheel in the car's own body
#: frame (+x = forward, +y = left). A reasonable default when a specific
#: car's real dimensions aren't known -- not a regulation constant, so
#: override half_wheelbase_m/half_track_m when they are.
DEFAULT_HALF_WHEELBASE_M = 1.8
DEFAULT_HALF_TRACK_M = 1.0

#: Wheel order: front-left, front-right, rear-left, rear-right.
_WHEEL_SIGNS = np.array([[1, 1], [1, -1], [-1, 1], [-1, -1]])


def wheel_world_positions(
    car_world_pos: tuple[float, float],
    heading_rad: float,
    half_wheelbase_m: float = DEFAULT_HALF_WHEELBASE_M,
    half_track_m: float = DEFAULT_HALF_TRACK_M,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Returns (front_left, front_right, rear_left, rear_right) world (x, y).

    heading_rad: the car's direction of travel, radians, standard math
    convention (0 = +x axis, increasing counter-clockwise) -- matches
    src.schemas.CarState.heading and src.track.frame.TrackFrame's
    direction convention.
    """
    offsets = _WHEEL_SIGNS * np.array([half_wheelbase_m, half_track_m])
    c, s = np.cos(heading_rad), np.sin(heading_rad)
    rotation = np.array([[c, -s], [s, c]])
    world = np.asarray(car_world_pos, dtype=float) + (rotation @ offsets.T).T
    return tuple(map(tuple, world))
