import pytest

from src.config import load_event_config
from src.rules.engine import RuleEngine
from src.schemas import EventType, Verdict
from tests.factories import make_event

CONFIG_PATH = "config/events/red_bull_ring_2023.yaml"


@pytest.fixture
def engine():
    return RuleEngine(load_event_config(CONFIG_PATH))


def test_clear_violation_carries_citations(engine):
    event = make_event(corner=1, wheels_off_peak=4, max_margin_m=0.30, margin_sigma_m=0.02)
    finding, verdict = engine.evaluate(event)
    assert verdict == Verdict.VIOLATION
    assert finding.violation is True
    assert finding.authority == ["F1SR Art. 33.3", "FIA Driving Standards Guidelines v4.1"]
    assert finding.exceptions_evaluated == {
        "forced_off": False,
        "avoidance": False,
        "already_penalized": False,
        "corner_not_monitored": False,
    }


def test_two_wheels_off_is_no_violation_with_exceptions_recorded(engine):
    event = make_event(corner=1, wheels_off_peak=2)
    finding, verdict = engine.evaluate(event)
    assert verdict == Verdict.NO_VIOLATION
    assert finding.violation is False
    assert finding.exceptions_evaluated["corner_not_monitored"] is False


def test_unmonitored_corner_never_becomes_a_violation(engine):
    # corner 2 is not in red_bull_ring_2023's monitored_corners
    event = make_event(corner=2, wheels_off_peak=4, max_margin_m=0.50, margin_sigma_m=0.01)
    finding, verdict = engine.evaluate(event)
    assert verdict == Verdict.NO_VIOLATION
    assert finding.corner_monitored is False
    assert finding.exceptions_evaluated["corner_not_monitored"] is True


def test_forced_off_excuses_a_four_wheel_excursion(engine):
    event = make_event(
        corner=1, wheels_off_peak=4, max_margin_m=0.40, margin_sigma_m=0.01,
        proposed_type=EventType.FORCED_OFF,
    )
    finding, verdict = engine.evaluate(event)
    assert verdict == Verdict.NO_VIOLATION
    assert finding.exceptions_evaluated["forced_off"] is True


def test_already_penalized_flag_is_caller_supplied_and_respected(engine):
    event = make_event(corner=1, wheels_off_peak=4, max_margin_m=0.40, margin_sigma_m=0.01)
    finding, verdict = engine.evaluate(event, already_penalized=True)
    assert verdict == Verdict.NO_VIOLATION
    assert finding.exceptions_evaluated["already_penalized"] is True


def test_marginal_evidence_abstains_rather_than_flags_or_clears(engine):
    event = make_event(corner=1, wheels_off_peak=4, max_margin_m=0.01, margin_sigma_m=0.02)
    finding, verdict = engine.evaluate(event)
    assert verdict == Verdict.INSUFFICIENT_EVIDENCE
    assert finding.violation is False  # abstain is never silently coded as "clean"


def test_engine_never_touches_strike_state(engine):
    event = make_event(corner=1, wheels_off_peak=4, max_margin_m=0.40, margin_sigma_m=0.01)
    finding, _ = engine.evaluate(event)
    assert finding.strike_context == "pending steward confirmation"
