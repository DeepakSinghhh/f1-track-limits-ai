import pytest

from src.audit.log import OverrideLog
from src.config import load_event_config
from src.rules.engine import RuleEngine
from src.rules.escalation import EscalationEngine, SessionType
from tests.factories import make_event

CONFIG_PATH = "config/events/red_bull_ring_2023.yaml"


@pytest.fixture
def config():
    return load_event_config(CONFIG_PATH)


@pytest.fixture
def override_log(tmp_path):
    return OverrideLog(tmp_path / "overrides.jsonl")


def make_violation_finding(config, corner=1):
    engine = RuleEngine(config)
    event = make_event(corner=corner, wheels_off_peak=4, max_margin_m=0.40, margin_sigma_m=0.01)
    finding, verdict = engine.evaluate(event)
    assert finding.violation is True
    return finding


def test_strikes_do_not_move_without_confirmation(config, override_log):
    escalation = EscalationEngine(config, override_log)
    make_violation_finding(config)
    # a Finding alone, with no increment_strike call, must not move strikes
    assert escalation.strikes_for(44) == 0


def test_increment_strike_requires_a_configured_log(config):
    escalation = EscalationEngine(config, override_log=None)
    finding = make_violation_finding(config)
    with pytest.raises(RuntimeError):
        escalation.increment_strike(finding, SessionType.RACE, steward_id="steward-1")


def test_practice_session_deletes_lap_time_on_first_strike(config, override_log):
    escalation = EscalationEngine(config, override_log)
    finding = make_violation_finding(config)
    result = escalation.increment_strike(finding, SessionType.PRACTICE, steward_id="steward-1")
    assert result.lap_time_deleted is True
    assert result.penalty_seconds == 0
    assert result.strikes == 1


def test_race_escalation_follows_event_notes_thresholds(config, override_log):
    escalation = EscalationEngine(config, override_log)
    results = []
    for _ in range(5):
        finding = make_violation_finding(config)
        results.append(escalation.increment_strike(finding, SessionType.RACE, steward_id="steward-1"))

    assert [r.strikes for r in results] == [1, 2, 3, 4, 5]
    assert results[2].black_and_white_flag is True   # 3rd strike
    assert results[3].penalty_seconds == 5            # 4th strike
    assert results[4].penalty_seconds == 10           # 5th strike
    assert results[0].black_and_white_flag is False
    assert results[0].penalty_seconds == 0


def test_reject_finding_never_adds_a_strike(config, override_log):
    escalation = EscalationEngine(config, override_log)
    finding = make_violation_finding(config)
    escalation.reject_finding(finding, steward_id="steward-1", rationale="review showed car was forced off")
    assert escalation.strikes_for(44) == 0


def test_every_confirmation_and_rejection_is_logged(config, override_log):
    escalation = EscalationEngine(config, override_log)
    v = make_violation_finding(config)
    escalation.increment_strike(v, SessionType.RACE, steward_id="steward-1", rationale="clear overshoot")
    r = make_violation_finding(config)
    escalation.reject_finding(r, steward_id="steward-2", rationale="replay showed 3 wheels off")

    records = override_log.read_all()
    assert len(records) == 2
    assert records[0]["human_decision"] == "violation"
    assert records[0]["strikes_after"] == 1
    assert records[1]["human_decision"] == "no_violation"
    assert records[1]["strikes_after"] is None
    assert records[0]["steward_id"] == "steward-1"
    assert records[1]["steward_id"] == "steward-2"
