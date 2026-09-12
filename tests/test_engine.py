import pytest

from src.config import load_event_config
from src.rules.engine import RuleEngine
from src.rules.session_state import SessionState
from src.schemas import EventType, Verdict
from tests.factories import make_event

CONFIG_PATH = "config/events/red_bull_ring_2023.yaml"


@pytest.fixture
def engine():
    return RuleEngine(load_event_config(CONFIG_PATH))


# --- The five required unit tests from Section 5.6, verbatim ---

def test_two_wheels_off_is_legal(engine):
    event = make_event(corner=1, wheels_off_peak=2, duration_s=0.62)
    finding, verdict = engine.evaluate(event)
    assert verdict == Verdict.NO_VIOLATION
    assert finding.violation is False


def test_four_wheels_off_for_100ms_is_an_artefact(engine):
    event = make_event(corner=1, wheels_off_peak=4, duration_s=0.10)
    finding, verdict = engine.evaluate(event)
    assert verdict == Verdict.NO_VIOLATION
    assert finding.violation is False
    assert "artefact" in finding.description


def test_four_wheels_off_for_600ms_on_a_monitored_corner_is_a_finding(engine):
    event = make_event(corner=1, wheels_off_peak=4, duration_s=0.62)  # corner 1 is monitored
    finding, verdict = engine.evaluate(event)
    assert verdict == Verdict.VIOLATION
    assert finding.violation is True


def test_same_on_an_unmonitored_corner_is_not_a_finding(engine):
    event = make_event(corner=2, wheels_off_peak=4, duration_s=0.62)  # corner 2 is not monitored
    finding, verdict = engine.evaluate(event)
    assert verdict == Verdict.NO_VIOLATION
    assert finding.violation is False
    assert finding.corner_monitored is False
    assert finding.exceptions_evaluated["corner_not_monitored"] is True


def test_forced_off_suppresses_the_finding(engine):
    event = make_event(
        corner=1, wheels_off_peak=4, duration_s=0.62, proposed_type=EventType.FORCED_OFF
    )
    finding, verdict = engine.evaluate(event)
    assert verdict == Verdict.NO_VIOLATION
    assert finding.violation is False
    assert finding.exceptions_evaluated["forced_off"] is True


# --- Additional coverage ---

def test_clear_violation_carries_citations(engine):
    event = make_event(corner=1, wheels_off_peak=4, duration_s=0.62)
    finding, verdict = engine.evaluate(event)
    assert verdict == Verdict.VIOLATION
    assert finding.authority == ["F1SR Art. 33.3", "FIA Driving Standards Guidelines v4.1"]
    assert finding.exceptions_evaluated == {
        "forced_off": False,
        "avoidance": False,
        "already_penalized": False,
        "corner_not_monitored": False,
    }


def test_already_penalized_is_read_from_session_state(engine):
    event = make_event(event_id="evt-99", corner=1, wheels_off_peak=4, duration_s=0.62)
    session_state = SessionState(penalized_event_ids=frozenset({"evt-99"}))
    finding, verdict = engine.evaluate(event, session_state=session_state)
    assert verdict == Verdict.NO_VIOLATION
    assert finding.exceptions_evaluated["already_penalized"] is True


def test_missing_wheel_data_is_insufficient_evidence_not_guessed(engine):
    event = make_event(corner=1, wheels_off_peak=None)
    finding, verdict = engine.evaluate(event)
    assert verdict == Verdict.INSUFFICIENT_EVIDENCE
    assert finding.violation is False


def test_engine_never_touches_strike_state(engine):
    event = make_event(corner=1, wheels_off_peak=4, duration_s=0.62)
    finding, _ = engine.evaluate(event)
    assert finding.strike_context == "pending steward confirmation"
