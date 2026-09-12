import numpy as np
import pytest

from src.track.build import build_straight_segment_track, build_track


def make_circle(radius=100.0, n=360):
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([radius * np.cos(theta), radius * np.sin(theta)], axis=1)


def test_build_track_recovers_known_track_width():
    reference = make_circle(radius=100.0, n=360)
    rng = np.random.default_rng(0)
    n_samples = 20000
    theta = rng.uniform(0, 2 * np.pi, n_samples)
    # Cars roam within a band from -4m to +4m either side of the centreline.
    lateral = rng.uniform(-4.0, 4.0, n_samples)
    radius = 100.0 + lateral
    x = radius * np.cos(theta)
    y = radius * np.sin(theta)

    frame, boundary = build_track(
        reference, x, y, white_line_width_m=0.0, edge_percentile=99.5, bin_size_m=5.0, smoothing_window=5
    )

    for s in np.linspace(0, frame.total_length, 20, endpoint=False):
        w_left, w_right = boundary.half_width(s)
        assert w_left == pytest.approx(4.0, abs=0.5)
        assert w_right == pytest.approx(4.0, abs=0.5)


def test_build_track_adds_white_line_width():
    reference = make_circle(radius=100.0, n=360)
    rng = np.random.default_rng(1)
    n_samples = 5000
    theta = rng.uniform(0, 2 * np.pi, n_samples)
    lateral = rng.uniform(-2.0, 2.0, n_samples)
    radius = 100.0 + lateral
    x = radius * np.cos(theta)
    y = radius * np.sin(theta)

    frame_no_line, boundary_no_line = build_track(reference, x, y, white_line_width_m=0.0)
    frame_with_line, boundary_with_line = build_track(reference, x, y, white_line_width_m=0.10)

    s = frame_no_line.total_length / 4
    w_left_a, _ = boundary_no_line.half_width(s)
    w_left_b, _ = boundary_with_line.half_width(s)
    assert w_left_b == pytest.approx(w_left_a + 0.10, abs=1e-9)


def test_rejects_empty_position_arrays():
    reference = make_circle()
    with pytest.raises(ValueError):
        build_track(reference, [], [], white_line_width_m=0.0)


def test_straight_segment_round_trips_near_the_segment():
    frame, _ = build_straight_segment_track(
        p1=(0.0, 0.0), p2=(100.0, 0.0), left_half_width_m=4.0, right_half_width_m=4.0, white_line_width_m=0.0
    )
    for s_offset in (10.0, 50.0, 90.0):
        for d in (-3.0, 0.0, 3.0):
            # s is measured from build_straight_segment_track's extended start, not p1 --
            # locate p1 first via to_frenet, then probe relative to it.
            p1_s, _ = frame.to_frenet(0.0, 0.0)
            x, y = frame.to_cartesian(p1_s + s_offset, d)
            s2, d2 = frame.to_frenet(x, y)
            assert abs(s2 - (p1_s + s_offset)) < 0.01
            assert abs(d2 - d) < 0.01


def test_straight_segment_half_width_matches_input_plus_white_line():
    frame, boundary = build_straight_segment_track(
        p1=(0.0, 0.0), p2=(100.0, 0.0), left_half_width_m=4.0, right_half_width_m=3.5, white_line_width_m=0.10
    )
    p1_s, _ = frame.to_frenet(0.0, 0.0)
    w_left, w_right = boundary.half_width(p1_s + 50.0)
    assert w_left == pytest.approx(4.10)
    assert w_right == pytest.approx(3.60)


def test_straight_segment_left_convention_matches_direction_of_travel():
    # p1 -> p2 travels along +x; a point at (50, 3) should read as "left" (+d)
    frame, _ = build_straight_segment_track(
        p1=(0.0, 0.0), p2=(100.0, 0.0), left_half_width_m=4.0, right_half_width_m=4.0, white_line_width_m=0.0
    )
    _, d = frame.to_frenet(50.0, 3.0)
    assert d == pytest.approx(3.0, abs=0.01)


def test_straight_segment_signed_distance_flags_outside_correctly():
    frame, boundary = build_straight_segment_track(
        p1=(0.0, 0.0), p2=(100.0, 0.0), left_half_width_m=4.0, right_half_width_m=4.0, white_line_width_m=0.0
    )
    s, d_inside = frame.to_frenet(50.0, 3.0)
    assert boundary.signed_distance_to_edge(s, d_inside) < 0

    s, d_outside = frame.to_frenet(50.0, 4.5)
    assert boundary.signed_distance_to_edge(s, d_outside) > 0


def test_straight_segment_stays_correct_for_a_wide_runoff_d():
    # regression guard: an earlier version used a hairline (0.05m) return-
    # path offset in the fabricated closed loop, which silently won the
    # nearest-segment search (and flipped both sign and s) for any |d|
    # beyond a couple of centimetres -- i.e. almost every real query.
    frame, boundary = build_straight_segment_track(
        p1=(0.0, 0.0), p2=(100.0, 0.0), left_half_width_m=4.0, right_half_width_m=4.0, white_line_width_m=0.0
    )
    p1_s, _ = frame.to_frenet(0.0, 0.0)
    for d in (10.0, 50.0, -50.0):
        x, y = frame.to_cartesian(p1_s + 40.0, d)
        s2, d2 = frame.to_frenet(x, y)
        assert abs(s2 - (p1_s + 40.0)) < 0.01
        assert abs(d2 - d) < 0.01


def test_straight_segment_rejects_identical_points():
    with pytest.raises(ValueError):
        build_straight_segment_track(
            p1=(5.0, 5.0), p2=(5.0, 5.0), left_half_width_m=4.0, right_half_width_m=4.0, white_line_width_m=0.0
        )
