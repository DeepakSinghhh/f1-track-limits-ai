"""Tier 3: LLM reasoning over the ambiguous slice (Section 5.8).

Runs on the ~120 items per race Tier 4 could not resolve with confidence
-- never on raw frames, never in place of the deterministic rule engine,
and never as the system's final word: this produces a recommendation, a
human steward still decides (Section 0).

The mandatory both-sides output template ("This template is a safety
control, not a formatting preference") is enforced with structured
outputs -- a JSON schema with all six fields required -- rather than by
hoping the model follows a text template. The flow is two phases: an
ordinary tool-use loop for research (get_telemetry, get_neighbouring_cars,
get_session_precedents, get_event_notes, get_driving_standards_guideline),
then one final call with no tools but a required schema, so the mandatory
fields are guaranteed present regardless of how the research phase ended.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import anthropic

from src.agent.tools import AgentContext, build_tools
from src.schemas import Finding, Verdict

MODEL = "claude-opus-5"
MAX_TOOL_ITERATIONS = 6

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "finding": {"type": "string", "description": "The finding restated in one or two sentences."},
        "case_for_violation": {"type": "string", "description": "The evidence-backed case that this was a violation."},
        "case_against": {"type": "string", "description": "The evidence-backed case that it was not."},
        "missing_evidence": {"type": "string", "description": "What would resolve this, if anything. Say 'none' if nothing would."},
        "precedents_this_session": {"type": "string", "description": "Relevant precedents retrieved, or 'none retrieved'."},
        "recommendation": {"type": "string", "enum": [v.value for v in Verdict]},
    },
    "required": [
        "finding",
        "case_for_violation",
        "case_against",
        "missing_evidence",
        "precedents_this_session",
        "recommendation",
    ],
    "additionalProperties": False,
}

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
    """The model's structured output didn't parse into a valid
    AgentReasoning. Surfaced, never silently downgraded to a guessed
    verdict -- an agent that can fail to answer is safer than one that
    always appears to.
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


def reason_about_finding(
    client: anthropic.Anthropic,
    finding: Finding,
    context: AgentContext,
    extra_instructions: str = "",
) -> AgentReasoning:
    schemas, dispatch = build_tools(context)

    user_prompt = _describe_finding(finding)
    if extra_instructions:
        user_prompt += f"\n{extra_instructions}\n"
    user_prompt += "\nUse the tools to gather context, then explain your reasoning."

    messages: list[dict] = [{"role": "user", "content": user_prompt}]

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=schemas,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            fn = dispatch.get(block.name)
            if fn is None:
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": f"Unknown tool {block.name!r}", "is_error": True}
                )
                continue
            try:
                result = fn(**block.input)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(result)})
            except Exception as exc:  # tool errors go back to the model, not raised here
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": str(exc), "is_error": True}
                )
        messages.append({"role": "user", "content": tool_results})
    else:
        messages.append({"role": "user", "content": "Tool research budget reached. Give your final recommendation now."})

    # Final pass: no tools, a required schema. This is what guarantees the
    # mandatory template regardless of how the research loop above ended.
    final = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=messages + [{"role": "user", "content": "Give your final structured recommendation now."}],
        output_config={"format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA}},
    )

    text = next((b.text for b in final.content if b.type == "text"), None)
    if text is None:
        raise MalformedAgentOutput("agent produced no text block on the final structured-output pass")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedAgentOutput(f"agent output was not valid JSON: {exc}") from exc

    try:
        return AgentReasoning(
            finding_restated=data["finding"],
            case_for_violation=data["case_for_violation"],
            case_against=data["case_against"],
            missing_evidence=data["missing_evidence"],
            precedents_this_session=data["precedents_this_session"],
            recommendation=Verdict(data["recommendation"]),
        )
    except (KeyError, ValueError) as exc:
        raise MalformedAgentOutput(f"agent output missing or invalid field: {exc}") from exc
