import numpy as np
import pytest

from src.track.boundary import Boundary
from src.track.frame import TrackFrame
from src.vision.project import apply_homography, project_boundary_edge

# A straight first segment (0,0) -> (10,0): to_cartesian(s, d) == (s, d)
# exactly for s in [0, 10], which makes the geometry trivial to reason
# about by hand.
CENTRELINE = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])

SCALE = 10.0
TX, TY = 50.0, 100.0
HOMOGRAPHY = np.array([[SCALE, 0, TX], [0, -SCALE, TY], [0, 0, 1]])


def make_flat_boundary(half_width=4.0, total_length=40.0):
    s_samples = np.linspace(0, total_length, 20, endpoint=False)
    half = np.full(20, half_width)
    return Boundary(s_samples, half, half, white_line_width_m=0.0, total_length=total_length)


def test_apply_homography_matches_expected_pixels():
    points = np.array([[5.0, 4.5], [5.0, -3.0]])
    uv = apply_homography(HOMOGRAPHY, points)
    assert uv[0] == pytest.approx([SCALE * 5.0 + TX, -SCALE * 4.5 + TY])
    assert uv[1] == pytest.approx([SCALE * 5.0 + TX, -SCALE * -3.0 + TY])


def test_apply_homography_single_point():
    uv = apply_homography(HOMOGRAPHY, np.array([5.0, 0.0]))
    assert uv.shape == (1, 2)
    assert uv[0] == pytest.approx([100.0, 100.0])


def test_project_boundary_edge_shape_and_range():
    frame_obj = TrackFrame(CENTRELINE)
    boundary = make_flat_boundary(half_width=4.0)
    # stay clear of s=10.0, an exact vertex between segments 0 and 1
    left = project_boundary_edge(frame_obj, boundary, 1.0, 9.0, "left", HOMOGRAPHY, n_samples=5)
    right = project_boundary_edge(frame_obj, boundary, 1.0, 9.0, "right", HOMOGRAPHY, n_samples=5)

    assert left.shape == (5, 2)
    assert right.shape == (5, 2)
    # left edge is at d=+4 -> v = -10*4 + 100 = 60; right edge at d=-4 -> v = 140
    assert left[:, 1] == pytest.approx(60.0)
    assert right[:, 1] == pytest.approx(140.0)


def test_project_boundary_edge_rejects_bad_side():
    frame_obj = TrackFrame(CENTRELINE)
    boundary = make_flat_boundary()
    with pytest.raises(ValueError):
        project_boundary_edge(frame_obj, boundary, 0.0, 10.0, "middle", HOMOGRAPHY)
