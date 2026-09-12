import json

import pytest

from src.agent.reason import MalformedAgentOutput, MAX_TOOL_ITERATIONS, reason_about_finding
from src.agent.tools import AgentContext
from src.config import load_event_config
from src.rules.engine import RuleEngine
from src.schemas import Verdict
from tests.factories import make_event
from tests.fake_groq import FakeClient, FakeMessage, FakeResponse, FakeToolCall, text_response, tool_call_response

CONFIG_PATH = "config/events/red_bull_ring_2023.yaml"

VALID_ANSWER = {
    "finding": "Car 44 ran wide at turn 1.",
    "case_for_violation": "Telemetry shows the car's position beyond the boundary for the full excursion.",
    "case_against": "No car was alongside; this looks like a straightforward mistake, not exploitation.",
    "missing_evidence": "none",
    "precedents_this_session": "none retrieved",
    "recommendation": "violation",
}


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
    assert len(client.chat.completions.calls) == 2


def test_final_call_has_no_tools_and_requests_json_mode():
    client = FakeClient([
        text_response("done"),
        text_response(json.dumps(VALID_ANSWER)),
    ])
    reason_about_finding(client, make_finding(), make_context())

    final_call_kwargs = client.chat.completions.calls[-1]
    assert "tools" not in final_call_kwargs
    assert final_call_kwargs["response_format"] == {"type": "json_object"}


def test_tool_call_is_dispatched_and_result_fed_back():
    client = FakeClient([
        tool_call_response("get_event_notes", {"circuit": "red_bull_ring"}),
        text_response("got the event notes"),
        text_response(json.dumps(VALID_ANSWER)),
    ])
    reason_about_finding(client, make_finding(), make_context())

    assert len(client.chat.completions.calls) == 3
    second_call_messages = client.chat.completions.calls[1]["messages"]
    tool_result_message = second_call_messages[-1]
    assert tool_result_message["role"] == "tool"
    assert tool_result_message["tool_call_id"] == "tool-1"
    assert "red_bull_ring" in tool_result_message["content"]


def test_assistant_tool_call_message_is_replayed_correctly():
    client = FakeClient([
        tool_call_response("get_event_notes", {"circuit": "x"}, tool_call_id="call-abc"),
        text_response("ok"),
        text_response(json.dumps(VALID_ANSWER)),
    ])
    reason_about_finding(client, make_finding(), make_context())

    second_call_messages = client.chat.completions.calls[1]["messages"]
    assistant_msg = [m for m in second_call_messages if m["role"] == "assistant"][-1]
    assert assistant_msg["tool_calls"][0]["id"] == "call-abc"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "get_event_notes"


def test_unknown_tool_name_reports_error_without_crashing():
    client = FakeClient([
        tool_call_response("not_a_real_tool", {}),
        text_response("ok"),
        text_response(json.dumps(VALID_ANSWER)),
    ])
    result = reason_about_finding(client, make_finding(), make_context())
    assert result.recommendation == Verdict.VIOLATION

    second_call_messages = client.chat.completions.calls[1]["messages"]
    tool_result = second_call_messages[-1]
    assert "Unknown tool" in tool_result["content"]


def test_tool_exception_reports_error_without_crashing():
    from src.agent.precedent import PrecedentStore

    context = AgentContext(config=load_event_config(CONFIG_PATH), precedents=PrecedentStore())
    client = FakeClient([
        # a non-empty precedent store is required to reach EventType(...)
        # instead of returning the tool's own "no store" message early
        tool_call_response("get_session_precedents", {"corner": 1, "event_type": "not_a_real_type"}),
        text_response("ok"),
        text_response(json.dumps(VALID_ANSWER)),
    ])
    result = reason_about_finding(client, make_finding(), context)
    assert result.recommendation == Verdict.VIOLATION

    second_call_messages = client.chat.completions.calls[1]["messages"]
    tool_result = second_call_messages[-1]
    assert "Error" in tool_result["content"]


def test_malformed_tool_call_arguments_json_reports_error_without_crashing():
    # arguments is not valid JSON at all -- json.loads itself must raise
    # cleanly and be caught, not crash the loop
    bad_tool_call = FakeToolCall("tool-1", "get_event_notes", {})
    bad_tool_call.function.arguments = "{not valid json"
    client = FakeClient([
        FakeResponse(finish_reason="tool_calls", message=FakeMessage(content=None, tool_calls=[bad_tool_call])),
        text_response("ok"),
        text_response(json.dumps(VALID_ANSWER)),
    ])
    result = reason_about_finding(client, make_finding(), make_context())
    assert result.recommendation == Verdict.VIOLATION

    second_call_messages = client.chat.completions.calls[1]["messages"]
    tool_result = second_call_messages[-1]
    assert "Error" in tool_result["content"]


def test_max_tool_iterations_is_respected():
    looping = [tool_call_response("get_event_notes", {"circuit": "x"}) for _ in range(MAX_TOOL_ITERATIONS)]
    client = FakeClient(looping + [text_response(json.dumps(VALID_ANSWER))])
    result = reason_about_finding(client, make_finding(), make_context())

    assert result.recommendation == Verdict.VIOLATION
    assert len(client.chat.completions.calls) == MAX_TOOL_ITERATIONS + 1


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


def test_no_content_on_final_pass_raises():
    client = FakeClient([
        text_response("done"),
        text_response(None),
    ])
    with pytest.raises(MalformedAgentOutput):
        reason_about_finding(client, make_finding(), make_context())
