import math

import pytest

from src.eval.metrics import (
    human_review_reduction,
    mean_flag_latency,
    precision_recall,
    risk_coverage_curve,
    steward_agreement_by_trust_band,
)
from src.schemas import Verdict

V = Verdict.VIOLATION
N = Verdict.NO_VIOLATION
IE = Verdict.INSUFFICIENT_EVIDENCE


def test_precision_recall_perfect_predictions():
    predicted = [V, V, N, N]
    actual = [V, V, N, N]
    result = precision_recall(predicted, actual)
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.true_positives == 2
    assert result.true_negatives == 2
    assert result.false_positives == 0
    assert result.false_negatives == 0


def test_precision_recall_missed_violation_counts_as_false_negative():
    predicted = [N, V]
    actual = [V, V]  # first one was actually a violation the system missed
    result = precision_recall(predicted, actual)
    assert result.false_negatives == 1
    assert result.recall == 0.5


def test_precision_recall_insufficient_evidence_is_not_a_positive_prediction():
    predicted = [IE]
    actual = [V]
    result = precision_recall(predicted, actual)
    assert result.false_negatives == 1
    assert result.true_positives == 0


def test_precision_recall_insufficient_evidence_against_a_true_negative_is_correct():
    predicted = [IE]
    actual = [N]
    result = precision_recall(predicted, actual)
    assert result.true_negatives == 1


def test_precision_recall_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        precision_recall([V], [V, N])


def test_precision_is_nan_with_no_positive_predictions():
    result = precision_recall([N, N], [V, N])
    assert math.isnan(result.precision)
    assert result.recall == 0.0


def test_steward_agreement_by_trust_band_basic():
    trust_scalars = [0.05, 0.15, 0.95, 0.92]
    system_verdicts = [V, V, V, N]
    steward_decisions = [N, V, V, N]  # first low-band item: disagreement
    result = steward_agreement_by_trust_band(trust_scalars, system_verdicts, steward_decisions, n_bands=5)
    assert result["0.0-0.2"] == 0.5  # 1 agree, 1 disagree in [0, 0.2)
    assert result["0.8-1.0"] == 1.0  # both agree


def test_steward_agreement_empty_band_is_nan_not_zero():
    trust_scalars = [0.9, 0.95]
    system_verdicts = [V, V]
    steward_decisions = [V, V]
    result = steward_agreement_by_trust_band(trust_scalars, system_verdicts, steward_decisions, n_bands=5)
    assert math.isnan(result["0.0-0.2"])
    assert result["0.8-1.0"] == 1.0


def test_steward_agreement_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        steward_agreement_by_trust_band([0.5], [V, N], [V])


def test_risk_coverage_curve_low_risk_at_low_coverage_for_a_good_signal():
    # confidence perfectly tracks correctness: high confidence = correct
    confidences = [0.99, 0.9, 0.8, 0.6, 0.4, 0.2, 0.1]
    correct = [True, True, True, True, False, False, False]
    curve = risk_coverage_curve(confidences, correct, n_points=10)

    assert len(curve) == 10
    coverages = [c for c, _ in curve]
    assert coverages == sorted(coverages)
    # risk at low coverage (most confident items) should be 0
    assert curve[0][1] == 0.0
    # risk at full coverage should equal the overall error rate (3/7)
    assert curve[-1][1] == pytest.approx(3 / 7, abs=0.05)


def test_risk_coverage_curve_rejects_empty_input():
    with pytest.raises(ValueError):
        risk_coverage_curve([], [])


def test_human_review_reduction_bounds():
    assert human_review_reduction(800, 120) == pytest.approx(1 - 120 / 800)
    assert human_review_reduction(800, 0) == 1.0
    assert human_review_reduction(800, 800) == 0.0


def test_human_review_reduction_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        human_review_reduction(0, 0)
    with pytest.raises(ValueError):
        human_review_reduction(10, 11)  # more reviewed than exist
    with pytest.raises(ValueError):
        human_review_reduction(10, -1)


def test_mean_flag_latency():
    event_times = [10.0, 20.0, 30.0]
    flag_times = [10.5, 20.2, 31.0]
    latency = mean_flag_latency(event_times, flag_times)
    assert latency == pytest.approx((0.5 + 0.2 + 1.0) / 3)


def test_mean_flag_latency_rejects_empty_or_mismatched():
    with pytest.raises(ValueError):
        mean_flag_latency([], [])
    with pytest.raises(ValueError):
        mean_flag_latency([1.0], [1.0, 2.0])
