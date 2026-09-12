"""One real call to the Anthropic API, proving the Tier 3 integration
actually works end-to-end (tool dispatch + the structured-output final
pass) rather than only against a scripted fake client. Skipped whenever
no API key is configured -- this is the only test in the suite that
costs money or needs network access, by design.
"""
import os

import anthropic
import pytest

from src.agent.reason import reason_about_finding
from src.agent.tools import AgentContext
from src.config import load_event_config
from src.rules.engine import RuleEngine
from src.schemas import Verdict
from tests.factories import make_event

CONFIG_PATH = "config/events/red_bull_ring_2023.yaml"

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set -- skipping the one live-API test",
)


def test_reason_about_finding_against_the_real_api():
    engine = RuleEngine(load_event_config(CONFIG_PATH))
    event = make_event(corner=1, wheels_off_peak=4, duration_s=0.62, max_margin_m=0.30, margin_sigma_m=0.02)
    finding, verdict = engine.evaluate(event)
    assert verdict == Verdict.VIOLATION  # sanity check on the fixture itself

    client = anthropic.Anthropic()
    context = AgentContext(config=load_event_config(CONFIG_PATH))

    result = reason_about_finding(
        client,
        finding,
        context,
        extra_instructions="Keep every field brief -- one or two sentences each.",
    )

    assert isinstance(result.recommendation, Verdict)
    assert result.finding_restated.strip() != ""
    assert result.case_for_violation.strip() != ""
    assert result.case_against.strip() != ""
    # the mandatory template's whole point: both sides present, not just one
    assert result.case_for_violation != result.case_against
