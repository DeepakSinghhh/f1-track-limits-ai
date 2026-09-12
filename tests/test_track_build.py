import numpy as np
import pytest

from src.track.build import build_track


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
