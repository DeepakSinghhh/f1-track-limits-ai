from src.rules.predicates import (
    describe_exception,
    evaluate_core_test,
    evaluate_exceptions,
    exception_applies,
)
from src.schemas import EventType, Verdict
from tests.factories import make_event


def test_four_wheels_off_with_clear_margin_is_violation():
    event = make_event(wheels_off_peak=4, max_margin_m=0.30, margin_sigma_m=0.02)
    verdict, reason = evaluate_core_test(event, min_confidence_sigma=2.0)
    assert verdict == Verdict.VIOLATION
    assert "all four wheels" in reason


def test_two_wheels_off_is_not_a_violation():
    event = make_event(wheels_off_peak=2)
    verdict, _ = evaluate_core_test(event, min_confidence_sigma=2.0)
    assert verdict == Verdict.NO_VIOLATION


def test_three_wheels_off_is_not_a_violation():
    event = make_event(wheels_off_peak=3)
    verdict, _ = evaluate_core_test(event, min_confidence_sigma=2.0)
    assert verdict == Verdict.NO_VIOLATION


def test_missing_wheel_data_is_insufficient_evidence():
    event = make_event(wheels_off_peak=None)
    verdict, reason = evaluate_core_test(event, min_confidence_sigma=2.0)
    assert verdict == Verdict.INSUFFICIENT_EVIDENCE
    assert "unavailable" in reason


def test_marginal_measurement_abstains_instead_of_guessing():
    # margin is only 1x sigma from the boundary: not distinguishable at 2 sigma
    event = make_event(wheels_off_peak=4, max_margin_m=0.02, margin_sigma_m=0.02)
    verdict, reason = evaluate_core_test(event, min_confidence_sigma=2.0)
    assert verdict == Verdict.INSUFFICIENT_EVIDENCE
    assert "σ" in reason


def test_zero_margin_and_zero_sigma_is_not_a_violation_by_point_estimate():
    event = make_event(wheels_off_peak=4, max_margin_m=0.0, margin_sigma_m=0.0)
    verdict, _ = evaluate_core_test(event, min_confidence_sigma=2.0)
    assert verdict == Verdict.INSUFFICIENT_EVIDENCE


def test_exceptions_are_all_reported_even_when_false():
    event = make_event(proposed_type=EventType.EXCURSION_NO_ADVANTAGE)
    result = evaluate_exceptions(event, corner_monitored=True, already_penalized=False)
    assert result == {
        "forced_off": False,
        "avoidance": False,
        "already_penalized": False,
        "corner_not_monitored": False,
    }
    assert exception_applies(result) is False


def test_forced_off_exception_applies():
    event = make_event(proposed_type=EventType.FORCED_OFF)
    result = evaluate_exceptions(event, corner_monitored=True, already_penalized=False)
    assert result["forced_off"] is True
    assert exception_applies(result) is True
    assert "forced_off" in describe_exception(result)


def test_unmonitored_corner_is_an_exception():
    event = make_event()
    result = evaluate_exceptions(event, corner_monitored=False, already_penalized=False)
    assert result["corner_not_monitored"] is True
    assert exception_applies(result) is True
