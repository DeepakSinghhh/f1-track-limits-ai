import cv2
import numpy as np
import pytest

from src.render.overlay import (
    FrameAnnotation,
    INSIDE_COLOR,
    OUTSIDE_COLOR,
    BOUNDARY_COLOR,
    draw_boundary_overlay,
    draw_contact_points,
    draw_margin_readout,
    draw_minimap_inset,
    draw_timeline_strip,
    render_incident_clip,
)
from src.track.boundary import Boundary
from src.track.frame import TrackFrame
from src.vision.project import apply_homography, project_boundary_edge
from tests.factories import make_event

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


def blank_frame(size=240):
    return np.full((size, size, 3), 20, dtype=np.uint8)


def test_draw_boundary_overlay_draws_boundary_colored_pixels():
    frame_obj = TrackFrame(CENTRELINE)
    boundary = make_flat_boundary(half_width=4.0)
    left = project_boundary_edge(frame_obj, boundary, 1.0, 9.0, "left", HOMOGRAPHY, n_samples=20)
    right = project_boundary_edge(frame_obj, boundary, 1.0, 9.0, "right", HOMOGRAPHY, n_samples=20)

    frame = blank_frame()
    draw_boundary_overlay(frame, left, right)

    mid_left = left[len(left) // 2].astype(int)
    assert tuple(frame[mid_left[1], mid_left[0]]) == BOUNDARY_COLOR


def test_draw_contact_points_colors_inside_and_outside():
    frame = blank_frame()
    points_uv = apply_homography(HOMOGRAPHY, np.array([[5.0, 4.5], [5.0, -3.0]]))
    draw_contact_points(frame, points_uv, outside_flags=[True, False], radius=6)

    u0, v0 = points_uv[0].astype(int)
    u1, v1 = points_uv[1].astype(int)
    assert tuple(frame[v0, u0]) == OUTSIDE_COLOR
    assert tuple(frame[v1, u1]) == INSIDE_COLOR


def test_draw_margin_readout_changes_pixels_without_erroring():
    frame = blank_frame()
    before = frame.copy()
    draw_margin_readout(frame, min_margin_m=-0.05, uncertainty_m=0.02)
    assert not np.array_equal(frame, before)


def test_draw_minimap_inset_pastes_into_top_right_region():
    frame_obj = TrackFrame(CENTRELINE)
    boundary = make_flat_boundary(half_width=4.0)
    frame = blank_frame(size=240)
    before = frame.copy()

    draw_minimap_inset(frame, frame_obj, boundary, s_center=5.0, s_window_m=8.0, trail_sd=[(4.0, 1.0), (5.0, 2.0)], size=100)

    top_right_region = frame[16:116, 240 - 116 : 240 - 16]
    before_region = before[16:116, 240 - 116 : 240 - 16]
    assert not np.array_equal(top_right_region, before_region)


def test_draw_minimap_inset_handles_empty_trail():
    frame_obj = TrackFrame(CENTRELINE)
    boundary = make_flat_boundary(half_width=4.0)
    frame = blank_frame()
    # must not raise even with no trail points yet (first frame of a clip)
    draw_minimap_inset(frame, frame_obj, boundary, s_center=5.0, s_window_m=8.0, trail_sd=[], size=100)


def test_draw_timeline_strip_draws_something_near_the_bottom():
    frame = blank_frame(size=240)
    before = frame.copy()
    draw_timeline_strip(frame, t_onset=1.0, t_max_excursion=1.2, t_reentry=1.6, t_current=1.3, clip_t_start=0.5, clip_t_end=2.0)
    bottom_row = frame[-20:, :]
    before_row = before[-20:, :]
    assert not np.array_equal(bottom_row, before_row)


def test_render_incident_clip_produces_a_readable_video(tmp_path):
    frame_obj = TrackFrame(CENTRELINE)
    boundary = make_flat_boundary(half_width=4.0)

    n_frames = 6
    frames = [blank_frame(size=240) for _ in range(n_frames)]
    annotations = [
        FrameAnnotation(
            session_time=0.1 * i,
            contact_points_xy=[(5.0 + 0.1 * i, 4.0 + 0.1 * i), (5.0 + 0.1 * i, -3.5)],
        )
        for i in range(n_frames)
    ]
    event = make_event(corner=1, wheels_off_peak=None, duration_s=0.6, max_margin_m=0.3, margin_sigma_m=0.02)

    output_path = str(tmp_path / "incident.mp4")
    result_path = render_incident_clip(
        frames, annotations, event, frame_obj, boundary, HOMOGRAPHY, output_path, fps=10.0
    )

    assert result_path.endswith(".mp4")

    cap = cv2.VideoCapture(result_path)
    assert cap.isOpened()
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == n_frames
    ret, first_frame = cap.read()
    assert ret
    assert first_frame.shape == (240, 240, 3)
    cap.release()


def test_render_incident_clip_rejects_mismatched_lengths(tmp_path):
    frame_obj = TrackFrame(CENTRELINE)
    boundary = make_flat_boundary()
    event = make_event()
    with pytest.raises(ValueError):
        render_incident_clip(
            [blank_frame()], [], event, frame_obj, boundary, HOMOGRAPHY, str(tmp_path / "x.mp4"), fps=10.0
        )


def test_render_incident_clip_rejects_empty_frames(tmp_path):
    frame_obj = TrackFrame(CENTRELINE)
    boundary = make_flat_boundary()
    event = make_event()
    with pytest.raises(ValueError):
        render_incident_clip([], [], event, frame_obj, boundary, HOMOGRAPHY, str(tmp_path / "x.mp4"), fps=10.0)
