import json

import pytest

from src.agent.reason import MalformedAgentOutput, MAX_TOOL_ITERATIONS, reason_about_finding
from src.agent.tools import AgentContext
from src.config import load_event_config
from src.rules.engine import RuleEngine
from src.schemas import Verdict
from tests.factories import make_event

CONFIG_PATH = "config/events/red_bull_ring_2023.yaml"

VALID_ANSWER = {
    "finding": "Car 44 ran wide at turn 1.",
    "case_for_violation": "Telemetry shows the car's position beyond the boundary for the full excursion.",
    "case_against": "No car was alongside; this looks like a straightforward mistake, not exploitation.",
    "missing_evidence": "none",
    "precedents_this_session": "none retrieved",
    "recommendation": "violation",
}


class FakeBlock:
    def __init__(self, type, **kwargs):
        self.type = type
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResponse:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeClient ran out of scripted responses")
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def text_response(text, stop_reason="end_turn"):
    return FakeResponse(stop_reason=stop_reason, content=[FakeBlock("text", text=text)])


def tool_use_response(name, input, tool_use_id="tool-1"):
    return FakeResponse(stop_reason="tool_use", content=[FakeBlock("tool_use", name=name, input=input, id=tool_use_id)])


def make_context():
    return AgentContext(config=load_event_config(CONFIG_PATH))


def make_finding():
    engine = RuleEngine(load_event_config(CONFIG_PATH))
    event = make_event(corner=1, wheels_off_peak=4, duration_s=0.62, max_margin_m=0.3)
    finding, _ = engine.evaluate(event)
    return finding


def test_no_tool_calls_returns_parsed_reasoning():
    client = FakeClient([
        text_response("no tools needed"),
        text_response(json.dumps(VALID_ANSWER)),
    ])
    result = reason_about_finding(client, make_finding(), make_context())

    assert result.recommendation == Verdict.VIOLATION
    assert result.case_for_violation == VALID_ANSWER["case_for_violation"]
    assert result.case_against == VALID_ANSWER["case_against"]
    assert len(client.messages.calls) == 2


def test_final_call_has_no_tools_and_a_required_schema():
    client = FakeClient([
        text_response("done"),
        text_response(json.dumps(VALID_ANSWER)),
    ])
    reason_about_finding(client, make_finding(), make_context())

    final_call_kwargs = client.messages.calls[-1]
    assert "tools" not in final_call_kwargs
    assert final_call_kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "recommendation" in final_call_kwargs["output_config"]["format"]["schema"]["required"]


def test_tool_call_is_dispatched_and_result_fed_back():
    client = FakeClient([
        tool_use_response("get_event_notes", {"circuit": "red_bull_ring"}),
        text_response("got the event notes"),
        text_response(json.dumps(VALID_ANSWER)),
    ])
    reason_about_finding(client, make_finding(), make_context())

    assert len(client.messages.calls) == 3
    # second call's messages must include the tool_result for the first tool_use
    second_call_messages = client.messages.calls[1]["messages"]
    tool_result_message = second_call_messages[-1]
    assert tool_result_message["role"] == "user"
    assert tool_result_message["content"][0]["type"] == "tool_result"
    assert tool_result_message["content"][0]["tool_use_id"] == "tool-1"
    assert "red_bull_ring" in tool_result_message["content"][0]["content"]


def test_unknown_tool_name_reports_error_without_crashing():
    client = FakeClient([
        tool_use_response("not_a_real_tool", {}),
        text_response("ok"),
        text_response(json.dumps(VALID_ANSWER)),
    ])
    result = reason_about_finding(client, make_finding(), make_context())
    assert result.recommendation == Verdict.VIOLATION

    second_call_messages = client.messages.calls[1]["messages"]
    tool_result = second_call_messages[-1]["content"][0]
    assert tool_result["is_error"] is True


def test_tool_exception_reports_error_without_crashing():
    from src.agent.precedent import PrecedentStore

    context = AgentContext(config=load_event_config(CONFIG_PATH), precedents=PrecedentStore())
    client = FakeClient([
        # a non-empty precedent store is required to reach EventType(...)
        # instead of returning the tool's own "no store" message early
        tool_use_response("get_session_precedents", {"corner": 1, "event_type": "not_a_real_type"}),
        text_response("ok"),
        text_response(json.dumps(VALID_ANSWER)),
    ])
    result = reason_about_finding(client, make_finding(), context)
    assert result.recommendation == Verdict.VIOLATION

    second_call_messages = client.messages.calls[1]["messages"]
    tool_result = second_call_messages[-1]["content"][0]
    assert tool_result["is_error"] is True


def test_max_tool_iterations_is_respected():
    looping = [tool_use_response("get_event_notes", {"circuit": "x"}) for _ in range(MAX_TOOL_ITERATIONS)]
    client = FakeClient(looping + [text_response(json.dumps(VALID_ANSWER))])
    result = reason_about_finding(client, make_finding(), make_context())

    assert result.recommendation == Verdict.VIOLATION
    assert len(client.messages.calls) == MAX_TOOL_ITERATIONS + 1


def test_malformed_json_raises_not_a_guessed_verdict():
    client = FakeClient([
        text_response("done"),
        text_response("this is not json"),
    ])
    with pytest.raises(MalformedAgentOutput):
        reason_about_finding(client, make_finding(), make_context())


def test_missing_required_field_raises():
    incomplete = dict(VALID_ANSWER)
    del incomplete["case_against"]
    client = FakeClient([
        text_response("done"),
        text_response(json.dumps(incomplete)),
    ])
    with pytest.raises(MalformedAgentOutput):
        reason_about_finding(client, make_finding(), make_context())


def test_invalid_recommendation_value_raises():
    bad = dict(VALID_ANSWER)
    bad["recommendation"] = "guilty"  # not a real Verdict value
    client = FakeClient([
        text_response("done"),
        text_response(json.dumps(bad)),
    ])
    with pytest.raises(MalformedAgentOutput):
        reason_about_finding(client, make_finding(), make_context())


def test_no_text_block_on_final_pass_raises():
    client = FakeClient([
        text_response("done"),
        FakeResponse(stop_reason="end_turn", content=[]),
    ])
    with pytest.raises(MalformedAgentOutput):
        reason_about_finding(client, make_finding(), make_context())
