import numpy as np
import pytest

from src.calibration import CalibrationError, calibrate


def test_calibrate_recovers_a_known_scale_and_translation():
    # world = 0.1 * pixel + (5, -2) -- no perspective distortion, easy to verify exactly
    image_points = [(0, 0), (1000, 0), (1000, 800), (0, 800)]
    world_points = [(x * 0.1 + 5, y * 0.1 - 2) for x, y in image_points]

    result = calibrate(image_points, world_points)

    for (u, v), (wx, wy) in zip(image_points, world_points):
        x, y = result.pixel_to_world(u, v)
        assert x == pytest.approx(wx, abs=1e-6)
        assert y == pytest.approx(wy, abs=1e-6)


def test_world_to_pixel_is_the_inverse_of_pixel_to_world():
    image_points = [(200, 400), (1000, 400), (1200, 700), (100, 700)]
    world_points = [(20, 0), (40, 0), (40, 15), (20, 15)]
    result = calibrate(image_points, world_points)

    for u, v in image_points:
        x, y = result.pixel_to_world(u, v)
        u2, v2 = result.world_to_pixel(x, y)
        assert u2 == pytest.approx(u, abs=1e-6)
        assert v2 == pytest.approx(v, abs=1e-6)


def test_reprojection_error_near_zero_for_exact_correspondences():
    image_points = [(200, 400), (1000, 400), (1200, 700), (100, 700)]
    world_points = [(20, 0), (40, 0), (40, 15), (20, 15)]
    result = calibrate(image_points, world_points)
    assert result.reprojection_error_px < 1e-6


def test_reprojection_error_reflects_inconsistent_points():
    # 5 points where one is deliberately off the true mapping -- least-
    # squares fit should show non-zero reprojection error
    image_points = [(0, 0), (100, 0), (100, 100), (0, 100), (50, 50)]
    world_points = [(0, 0), (10, 0), (10, 10), (0, 10), (9, 9)]  # last point inconsistent
    result = calibrate(image_points, world_points)
    assert result.reprojection_error_px > 0.5


def test_calibrate_requires_at_least_four_points():
    with pytest.raises(CalibrationError):
        calibrate([(0, 0), (1, 0), (1, 1)], [(0, 0), (1, 0), (1, 1)])


def test_calibrate_rejects_mismatched_lengths():
    with pytest.raises(CalibrationError):
        calibrate([(0, 0), (1, 0), (1, 1), (0, 1)], [(0, 0), (1, 0), (1, 1)])


def test_calibrate_rejects_collinear_points():
    collinear_image = [(0, 0), (10, 0), (20, 0), (30, 0)]
    collinear_world = [(0, 0), (1, 0), (2, 0), (3, 0)]
    with pytest.raises(CalibrationError):
        calibrate(collinear_image, collinear_world)
