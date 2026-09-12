import math

import numpy as np
import pytest

from src.track.boundary import Boundary
from src.track.frame import TrackFrame
from src.vision.contact import wheel_margins, wheel_world_positions

# Straight segment (0,0) -> (10,0): to_cartesian(s, d) == (s, d) for s in
# [0, 10], matching tests/test_vision_project.py's own fixture.
CENTRELINE = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])


def make_flat_boundary(half_width=4.0, total_length=40.0):
    s_samples = np.linspace(0, total_length, 20, endpoint=False)
    half = np.full(20, half_width)
    return Boundary(s_samples, half, half, white_line_width_m=0.0, total_length=total_length)


def test_wheel_order_and_offsets_at_zero_heading():
    fl, fr, rl, rr = wheel_world_positions((0.0, 0.0), heading_rad=0.0, half_wheelbase_m=2.0, half_track_m=1.0)
    assert fl == pytest.approx((2.0, 1.0))
    assert fr == pytest.approx((2.0, -1.0))
    assert rl == pytest.approx((-2.0, 1.0))
    assert rr == pytest.approx((-2.0, -1.0))


def test_wheel_positions_translate_with_car_position():
    fl, fr, rl, rr = wheel_world_positions((100.0, 50.0), heading_rad=0.0, half_wheelbase_m=2.0, half_track_m=1.0)
    assert fl == pytest.approx((102.0, 51.0))
    assert rr == pytest.approx((98.0, 49.0))


def test_wheel_positions_rotate_with_heading_90_degrees():
    # heading = +90deg (pi/2): "forward" (+x in body frame) now points along +y in world
    fl, fr, rl, rr = wheel_world_positions((0.0, 0.0), heading_rad=math.pi / 2, half_wheelbase_m=2.0, half_track_m=1.0)
    assert fl[0] == pytest.approx(-1.0, abs=1e-9)
    assert fl[1] == pytest.approx(2.0, abs=1e-9)
    assert fr[0] == pytest.approx(1.0, abs=1e-9)
    assert fr[1] == pytest.approx(2.0, abs=1e-9)


def test_default_dimensions_are_reasonable_f1_scale():
    fl, fr, rl, rr = wheel_world_positions((0.0, 0.0), heading_rad=0.0)
    # wheelbase and track width should be in a plausible metre range, not a
    # bounding-box centroid stand-in (0,0 for every wheel)
    assert fl != (0.0, 0.0)
    wheelbase = fl[0] - rl[0]
    track_width = fl[1] - fr[1]
    assert 2.0 < wheelbase < 6.0
    assert 1.0 < track_width < 3.0


def test_all_four_wheels_are_distinct_points():
    wheels = wheel_world_positions((10.0, 10.0), heading_rad=0.3)
    assert len(set(wheels)) == 4


def test_wheel_margins_matches_boundary_signed_distance():
    frame_obj = TrackFrame(CENTRELINE)
    boundary = make_flat_boundary(half_width=4.0)
    margins = wheel_margins(frame_obj, boundary, [(5.0, 4.5), (5.0, -3.0)])
    assert margins[0] == pytest.approx(0.5)   # 4.5 - 4.0, outside
    assert margins[1] == pytest.approx(-1.0)  # -(-3.0) - 4.0, inside
