import json

from src.agent.tools import AgentContext
from src.config import load_event_config
from src.review_queue import AGENT_TRUST_THRESHOLD, annotate_findings
from src.rules.engine import RuleEngine
from src.schemas import Verdict
from tests.factories import make_event
from tests.fake_groq import FakeClient, text_response

CONFIG_PATH = "config/events/red_bull_ring_2023.yaml"

VALID_AGENT_ANSWER = {
    "finding": "Car 44 ran wide at turn 1.",
    "case_for_violation": "Telemetry shows the car beyond the boundary for the full excursion.",
    "case_against": "No car was alongside; looks like a mistake, not exploitation.",
    "missing_evidence": "none",
    "precedents_this_session": "none retrieved",
    "recommendation": "violation",
}


def make_finding_tuple(**overrides):
    engine = RuleEngine(load_event_config(CONFIG_PATH))
    event = make_event(**overrides)
    finding, verdict = engine.evaluate(event)
    return event, finding, verdict


def make_context():
    return AgentContext(config=load_event_config(CONFIG_PATH))


def test_high_trust_finding_keeps_tier2_verdict_and_skips_agent():
    triple = make_finding_tuple(
        corner=1, wheels_off_peak=4, max_margin_m=0.30, margin_sigma_m=0.02, duration_s=0.62
    )
    fake_agent = FakeClient([text_response(json.dumps(VALID_AGENT_ANSWER))])

    [result] = annotate_findings(
        [triple], reproj_error_px=1.0, agent_context=make_context(), agent_client=fake_agent
    )

    assert result.trust.scalar >= AGENT_TRUST_THRESHOLD
    assert result.display_verdict == result.verdict == Verdict.VIOLATION
    assert result.agent_reasoning is None
    assert len(fake_agent.chat.completions.calls) == 0


def test_low_trust_finding_is_downgraded_and_triggers_the_agent():
    # tiny margin relative to its uncertainty *and* a poor reprojection
    # error -- both measurement_margin and evidence_quality pull the
    # scalar below threshold, not just one component in isolation
    triple = make_finding_tuple(
        corner=1, wheels_off_peak=4, max_margin_m=0.01, margin_sigma_m=5.0, duration_s=0.62
    )
    fake_agent = FakeClient(
        [text_response("no tools needed"), text_response(json.dumps(VALID_AGENT_ANSWER))]
    )

    [result] = annotate_findings(
        [triple], reproj_error_px=15.0, agent_context=make_context(), agent_client=fake_agent
    )

    assert result.trust.scalar < AGENT_TRUST_THRESHOLD
    assert result.verdict == Verdict.VIOLATION  # Tier 2's own finding, untouched
    assert result.display_verdict == Verdict.INSUFFICIENT_EVIDENCE  # Tier 4's downgrade
    assert result.agent_reasoning is not None
    assert "FINDING:" in result.agent_reasoning
    assert "RECOMMENDATION: violation" in result.agent_reasoning
    assert len(fake_agent.chat.completions.calls) == 2


def test_no_agent_client_means_reasoning_always_none_even_on_low_trust():
    triple = make_finding_tuple(
        corner=1, wheels_off_peak=4, max_margin_m=0.01, margin_sigma_m=5.0, duration_s=0.62
    )

    [result] = annotate_findings(
        [triple], reproj_error_px=15.0, agent_context=make_context(), agent_client=None
    )

    assert result.trust.scalar < AGENT_TRUST_THRESHOLD
    assert result.agent_reasoning is None


def test_agent_failure_is_isolated_and_never_raises():
    triple = make_finding_tuple(
        corner=1, wheels_off_peak=4, max_margin_m=0.01, margin_sigma_m=5.0, duration_s=0.62
    )
    fake_agent = FakeClient([])  # no scripted responses -- first call raises inside the fake

    [result] = annotate_findings(
        [triple], reproj_error_px=15.0, agent_context=make_context(), agent_client=fake_agent
    )

    assert result.agent_reasoning is None
    assert result.display_verdict == Verdict.INSUFFICIENT_EVIDENCE


def test_precedent_consistency_accumulates_per_corner_in_order():
    # first item at corner 1 has no prior verdicts -> neutral precedent score
    first = make_finding_tuple(
        event_id="evt-1", corner=1, wheels_off_peak=4, max_margin_m=0.30, margin_sigma_m=0.02
    )
    # second item, same corner, same verdict -> full agreement (1.0)
    second = make_finding_tuple(
        event_id="evt-2", corner=1, wheels_off_peak=4, max_margin_m=0.28, margin_sigma_m=0.02
    )
    # third item, a *different* corner -> still no prior verdicts of its own
    third = make_finding_tuple(
        event_id="evt-3", corner=7, wheels_off_peak=4, max_margin_m=0.30, margin_sigma_m=0.02
    )

    results = annotate_findings(
        [first, second, third], reproj_error_px=1.0, agent_context=make_context(), agent_client=None
    )

    assert results[0].trust.precedent_consistency == 1.0  # no precedents yet -> neutral
    assert results[1].trust.precedent_consistency == 1.0  # agrees with the one prior verdict at corner 1
    assert results[2].trust.precedent_consistency == 1.0  # corner 7 has no precedents of its own yet


def test_reproj_error_px_none_is_handled_for_the_uncalibrated_path():
    triple = make_finding_tuple(corner=1, wheels_off_peak=4, max_margin_m=0.30, margin_sigma_m=0.02)

    [result] = annotate_findings(
        [triple], reproj_error_px=None, agent_context=make_context(), agent_client=None
    )

    assert 0.0 <= result.trust.evidence_quality <= 1.0
