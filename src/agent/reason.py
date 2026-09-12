"""Tier 3: LLM reasoning over the ambiguous slice (Section 5.8).

Runs on the ~120 items per race Tier 4 could not resolve with confidence
-- never on raw frames, never in place of the deterministic rule engine,
and never as the system's final word: this produces a recommendation, a
human steward still decides (Section 0).

Provider: Groq (OpenAI-compatible chat-completions API), per this
project's explicit choice -- NOT the "Model: Claude via API" the plan
text names in Section 5.8. Two consequences of that swap worth keeping
in mind when reading this module:

- Tool call arguments arrive as a JSON *string*
  (`tool_call.function.arguments`), not a pre-parsed dict the way
  Anthropic's `tool_use.input` is -- every dispatch here does its own
  `json.loads`.
- Groq's `response_format={"type": "json_object"}` guarantees syntactically
  valid JSON, but -- unlike Anthropic's `output_config.format` json_schema
  -- does not itself enforce which keys are present. The mandatory
  both-sides template ("a safety control, not a formatting preference")
  is therefore enforced here by strict client-side validation after the
  call: every required field is checked and `recommendation` is validated
  against the real Verdict enum, raising MalformedAgentOutput on any
  deviation rather than silently accepting a partial answer. This is the
  same guarantee the schema gave server-side on Anthropic, just enforced
  on this side of the API boundary instead of the other.

Not live-verified: this sandbox's egress policy blocks api.groq.com, so
only the fake-client tests (tests/test_agent_reason.py) have actually
exercised this code. Run it against a real key outside this sandbox
before trusting it in production.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import groq

from src.agent.tools import AgentContext, build_tools
from src.schemas import Finding, Verdict

#: Verify against Groq's current model catalog
#: (https://console.groq.com/docs/models) before deploying -- could not
#: be checked live from this sandbox. Needs tool-calling support.
MODEL = "llama-3.3-70b-versatile"
MAX_TOOL_ITERATIONS = 6

_REQUIRED_FIELDS = (
    "finding",
    "case_for_violation",
    "case_against",
    "missing_evidence",
    "precedents_this_session",
    "recommendation",
)

_OUTPUT_SCHEMA_DESCRIPTION = """Respond with ONLY a JSON object (no other text) with exactly these keys:
{
  "finding": "<the finding restated in one or two sentences>",
  "case_for_violation": "<the evidence-backed case that this was a violation>",
  "case_against": "<the evidence-backed case that it was not>",
  "missing_evidence": "<what would resolve this, if anything -- say 'none' if nothing would>",
  "precedents_this_session": "<relevant precedents retrieved, or 'none retrieved'>",
  "recommendation": "<one of: violation, no_violation, insufficient_evidence>"
}"""

SYSTEM_PROMPT = (
    "You are an advisory reviewer for an F1 steward-assist system. You are shown one "
    "ambiguous track-limits finding that automated tiers could not resolve with confidence. "
    "Research it using the tools available, then give a recommendation. You never decide the "
    "case and no penalty or strike follows automatically from anything you write -- a human "
    "steward makes the final call. You MUST argue both sides explicitly, even when you are "
    "fairly confident: state the case FOR a violation and the case AGAINST it, using specific "
    "evidence from the tools you called, not generic language. If nothing meaningfully "
    "supports one side, say so plainly in that field rather than inventing a weak argument or "
    "leaving it blank."
)


@dataclass(frozen=True)
class AgentReasoning:
    finding_restated: str
    case_for_violation: str
    case_against: str
    missing_evidence: str
    precedents_this_session: str
    recommendation: Verdict


class MalformedAgentOutput(RuntimeError):
    """The model's output didn't parse into a valid AgentReasoning.
    Surfaced, never silently downgraded to a guessed verdict -- an agent
    that can fail to answer is safer than one that always appears to.
    """


def _describe_finding(finding: Finding) -> str:
    return (
        f"Finding under review:\n"
        f"- event_id: {finding.event_id}\n"
        f"- car: {finding.car_number}, lap {finding.lap}, corner {finding.corner}\n"
        f"- session time: {finding.session_time}\n"
        f"- description: {finding.description}\n"
        f"- authority: {', '.join(finding.authority)}\n"
        f"- exceptions evaluated: {finding.exceptions_evaluated}\n"
        f"- margin: {finding.min_margin_cm:.1f}cm (+/-{finding.margin_uncertainty_cm:.1f}cm)\n"
    )


def _to_groq_tools(schemas: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["input_schema"],
            },
        }
        for s in schemas
    ]


def reason_about_finding(
    client: groq.Groq,
    finding: Finding,
    context: AgentContext,
    extra_instructions: str = "",
) -> AgentReasoning:
    schemas, dispatch = build_tools(context)
    groq_tools = _to_groq_tools(schemas)

    user_prompt = _describe_finding(finding)
    if extra_instructions:
        user_prompt += f"\n{extra_instructions}\n"
    user_prompt += "\nUse the tools to gather context, then explain your reasoning."

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    for _ in range(MAX_TOOL_ITERATIONS):
        # A snapshot copy, not `messages` itself: `messages` keeps growing
        # after this call is made, and passing the live list would mean a
        # caller that logs/inspects create()'s kwargs later (this
        # module's own tests included) sees a list mutated by everything
        # that happened after, not what was actually sent at this point.
        response = client.chat.completions.create(
            model=MODEL,
            messages=list(messages),
            tools=groq_tools,
            tool_choice="auto",
        )
        choice = response.choices[0]

        if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
            break

        assistant_msg = {
            "role": "assistant",
            "content": choice.message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in choice.message.tool_calls
            ],
        }
        messages.append(assistant_msg)

        for tc in choice.message.tool_calls:
            fn = dispatch.get(tc.function.name)
            if fn is None:
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": f"Unknown tool {tc.function.name!r}"}
                )
                continue
            try:
                kwargs = json.loads(tc.function.arguments)
                result = fn(**kwargs)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
            except Exception as exc:  # tool errors go back to the model, not raised here
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"Error: {exc}"})
    else:
        messages.append(
            {"role": "user", "content": "Tool research budget reached. Give your final recommendation now."}
        )

    # Final pass: no tools, JSON mode, with the required schema spelled out
    # in the prompt -- see the module docstring for why this is validated
    # client-side rather than server-enforced on this provider. Builds a
    # new list rather than mutating `messages` in place, so a caller that
    # inspects/logs each create() call's kwargs afterward (this module's
    # own tests included) sees what was actually sent at that point, not
    # a list mutated by everything that happened after.
    final_messages = messages + [
        {"role": "user", "content": f"Give your final recommendation now.\n\n{_OUTPUT_SCHEMA_DESCRIPTION}"}
    ]
    final = client.chat.completions.create(
        model=MODEL,
        messages=final_messages,
        response_format={"type": "json_object"},
    )

    text = final.choices[0].message.content
    if not text:
        raise MalformedAgentOutput("agent produced no content on the final JSON-mode pass")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedAgentOutput(f"agent output was not valid JSON: {exc}") from exc

    missing = [f for f in _REQUIRED_FIELDS if f not in data]
    if missing:
        raise MalformedAgentOutput(f"agent output missing required field(s): {missing}")

    try:
        return AgentReasoning(
            finding_restated=data["finding"],
            case_for_violation=data["case_for_violation"],
            case_against=data["case_against"],
            missing_evidence=data["missing_evidence"],
            precedents_this_session=data["precedents_this_session"],
            recommendation=Verdict(data["recommendation"]),
        )
    except ValueError as exc:
        raise MalformedAgentOutput(f"agent output had an invalid recommendation value: {exc}") from exc
