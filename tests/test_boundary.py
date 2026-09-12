import numpy as np
import pytest

from src.track.boundary import Boundary


def make_flat_boundary(width_left=4.0, width_right=4.0, white_line=0.10, total_length=100.0):
    s_samples = np.linspace(0, total_length, 20, endpoint=False)
    left = np.full(20, width_left)
    right = np.full(20, width_right)
    return Boundary(s_samples, left, right, white_line, total_length)


def test_half_width_adds_white_line_width_to_painted_edge():
    boundary = make_flat_boundary(width_left=4.0, width_right=4.0, white_line=0.10)
    w_left, w_right = boundary.half_width(10.0)
    assert w_left == pytest.approx(4.10)
    assert w_right == pytest.approx(4.10)


def test_signed_distance_negative_inside_track():
    boundary = make_flat_boundary()
    assert boundary.signed_distance_to_edge(10.0, 0.0) < 0
    assert boundary.signed_distance_to_edge(10.0, 2.0) < 0


def test_signed_distance_positive_beyond_outer_edge():
    boundary = make_flat_boundary(width_left=4.0, width_right=4.0, white_line=0.10)
    d_out = boundary.signed_distance_to_edge(10.0, 4.5)
    assert d_out == pytest.approx(4.5 - 4.10)


def test_signed_distance_right_side_uses_right_width():
    boundary = make_flat_boundary(width_left=4.0, width_right=3.0, white_line=0.10)
    assert boundary.signed_distance_to_edge(10.0, -3.5) == pytest.approx(3.5 - 3.10)


def test_half_width_wraps_across_start_finish():
    boundary = make_flat_boundary(total_length=100.0)
    w_left_a, _ = boundary.half_width(-1.0)
    w_left_b, _ = boundary.half_width(99.0)
    assert w_left_a == pytest.approx(w_left_b)
