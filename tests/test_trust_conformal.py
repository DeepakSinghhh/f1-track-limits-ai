import numpy as np
import pytest

from src.schemas import Verdict
from src.trust.conformal import fit_conformal_quantile, predict_set


def test_confident_correct_scores_give_singleton_sets():
    rng = np.random.default_rng(0)
    n = 1000
    labels = rng.binomial(1, 0.5, n)
    # a near-perfect model: score close to the true label
    cal_scores = np.where(labels == 1, rng.uniform(0.9, 0.99, n), rng.uniform(0.01, 0.1, n))

    q_hat = fit_conformal_quantile(cal_scores, labels, alpha=0.05)

    confident_violation = predict_set(0.97, q_hat)
    confident_clean = predict_set(0.03, q_hat)
    assert confident_violation == [Verdict.VIOLATION]
    assert confident_clean == [Verdict.NO_VIOLATION]


def test_marginal_score_gives_an_ambiguous_two_element_set():
    rng = np.random.default_rng(0)
    n = 1000
    labels = rng.binomial(1, 0.5, n)
    cal_scores = np.where(labels == 1, rng.uniform(0.9, 0.99, n), rng.uniform(0.01, 0.1, n))
    q_hat = fit_conformal_quantile(cal_scores, labels, alpha=0.05)

    ambiguous = predict_set(0.5, q_hat)
    assert set(ambiguous) == {Verdict.VIOLATION, Verdict.NO_VIOLATION}


def test_empirical_coverage_is_close_to_target():
    rng = np.random.default_rng(42)
    n_cal, n_test = 2000, 2000
    alpha = 0.1

    def sample(n):
        labels = rng.binomial(1, 0.5, n)
        scores = np.clip(
            np.where(labels == 1, rng.normal(0.75, 0.15, n), rng.normal(0.25, 0.15, n)), 0, 1
        )
        return scores, labels

    cal_scores, cal_labels = sample(n_cal)
    q_hat = fit_conformal_quantile(cal_scores, cal_labels, alpha=alpha)

    test_scores, test_labels = sample(n_test)
    covered = 0
    for score, label in zip(test_scores, test_labels):
        pred = predict_set(score, q_hat)
        true_verdict = Verdict.VIOLATION if label == 1 else Verdict.NO_VIOLATION
        if true_verdict in pred:
            covered += 1

    coverage = covered / n_test
    assert coverage >= (1 - alpha) - 0.05  # distribution-free guarantee, with sampling slack


def test_rejects_empty_calibration_set():
    with pytest.raises(ValueError):
        fit_conformal_quantile([], [])
