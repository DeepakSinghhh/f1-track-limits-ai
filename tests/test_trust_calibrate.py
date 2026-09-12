import numpy as np
import pytest

from src.trust.calibrate import IsotonicCalibrator, expected_calibration_error


def test_isotonic_calibrator_is_monotonic_non_decreasing():
    rng = np.random.default_rng(0)
    n = 500
    raw_scores = rng.uniform(0, 1, n)
    # true probability of violation is monotonic in raw_scores; labels are noisy draws
    true_p = raw_scores
    labels = rng.binomial(1, true_p)

    calibrator = IsotonicCalibrator().fit(raw_scores, labels)
    test_points = np.linspace(0, 1, 20)
    predicted = calibrator.predict(test_points)
    assert np.all(np.diff(predicted) >= -1e-9)  # non-decreasing


def test_isotonic_calibrator_improves_ece_on_a_biased_raw_score():
    rng = np.random.default_rng(1)
    n = 2000
    true_p = rng.uniform(0, 1, n)
    labels = rng.binomial(1, true_p)
    # a raw "confidence" that is systematically overconfident: pushed toward the extremes
    raw_scores = np.clip(0.5 + 1.8 * (true_p - 0.5), 0, 1)

    ece_before = expected_calibration_error(raw_scores, labels)

    calibrator = IsotonicCalibrator().fit(raw_scores, labels)
    calibrated = calibrator.predict(raw_scores)
    ece_after = expected_calibration_error(calibrated, labels)

    assert ece_after < ece_before


def test_calibrator_requires_fit_before_predict():
    with pytest.raises(RuntimeError):
        IsotonicCalibrator().predict([0.5])


def test_calibrator_rejects_empty_calibration_set():
    with pytest.raises(ValueError):
        IsotonicCalibrator().fit([], [])


def test_ece_near_zero_for_a_perfectly_calibrated_predictor():
    rng = np.random.default_rng(2)
    n = 5000
    probs = rng.uniform(0, 1, n)
    labels = rng.binomial(1, probs)
    ece = expected_calibration_error(probs, labels, n_bins=10)
    assert ece < 0.05
