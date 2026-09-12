import numpy as np
import pytest

from src.track.frame import TrackFrame


def make_circle(radius=100.0, n=720):
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([radius * np.cos(theta), radius * np.sin(theta)], axis=1)


def _wrapped_diff(a, b, period):
    d = abs(a - b) % period
    return min(d, period - d)


def test_total_length_matches_circle_circumference():
    frame = TrackFrame(make_circle(radius=100.0, n=1440))
    assert frame.total_length == pytest.approx(2 * np.pi * 100.0, rel=1e-3)


def test_round_trip_on_centreline():
    # Acceptance criterion (Section 5.1): round-trip within 0.05m across the lap.
    frame = TrackFrame(make_circle(radius=100.0, n=720))
    for s in np.linspace(0, frame.total_length, 50, endpoint=False):
        x, y = frame.to_cartesian(s, 0.0)
        s2, d2 = frame.to_frenet(x, y)
        assert _wrapped_diff(s2, s, frame.total_length) < 0.05
        assert abs(d2) < 0.05


def test_round_trip_off_centreline():
    frame = TrackFrame(make_circle(radius=100.0, n=720))
    for s in np.linspace(0, frame.total_length, 30, endpoint=False):
        for d in (-3.0, -0.5, 0.5, 3.0):
            x, y = frame.to_cartesian(s, d)
            s2, d2 = frame.to_frenet(x, y)
            assert _wrapped_diff(s2, s, frame.total_length) < 0.05
            assert abs(d2 - d) < 0.05


def test_wrap_around_start_finish():
    frame = TrackFrame(make_circle(radius=100.0, n=720))
    x, y = frame.to_cartesian(-1.0, 0.0)
    x2, y2 = frame.to_cartesian(frame.total_length - 1.0, 0.0)
    assert x == pytest.approx(x2, abs=1e-9)
    assert y == pytest.approx(y2, abs=1e-9)


def test_left_is_positive_d_convention():
    # First segment travels +x; left of that direction of travel is +y.
    centreline = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    frame = TrackFrame(centreline)
    x, y = frame.to_cartesian(5.0, 2.0)
    assert y == pytest.approx(2.0, abs=1e-9)


def test_rejects_degenerate_centreline():
    with pytest.raises(ValueError):
        TrackFrame(np.array([[0.0, 0.0], [0.0, 0.0], [1.0, 1.0]]))
    with pytest.raises(ValueError):
        TrackFrame(np.array([[0.0, 0.0], [1.0, 1.0]]))  # fewer than 3 points
