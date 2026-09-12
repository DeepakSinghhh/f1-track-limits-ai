"""Tools exposed to the Tier 3 reasoning agent (Section 5.8).

Runs on ~120 ambiguous items per race, not on frames -- these give the
agent read-only access to exactly the context a steward would pull up
themselves: telemetry around the incident, who else was on track, how
comparable events were called earlier this session, and the regulations
in force. None of them let the agent write anything: Tier 3 recommends,
it never decides or applies a consequence (Section 0).

Raw tool schemas + a name->callable dispatch, rather than the SDK's
@beta_tool/tool_runner helpers: src.agent.reason runs a manual loop so it
can switch to a tools-free, structured-output-only final call once
research is done (see that module's docstring for why).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.agent.precedent import PrecedentStore
from src.config import EventConfig
from src.schemas import CarState, EventType

#: Local paraphrases of a few FIA Driving Standards Guidelines topics this
#: project's exceptions reference (Section 1.2) -- NOT verbatim text, and
#: not a substitute for the actual published Guidelines. Written here
#: because a real copy isn't bundled with this repo; keeping the tool
#: honest about that is the whole point of the disclaimer this returns.
_GUIDELINE_SUMMARIES = {
    "forced_off": (
        "A driver forced off the track by another car's manoeuvre is not judged to have "
        "left the track without justifiable reason (F1SR Art. 33.3 exception)."
    ),
    "avoidance": (
        "Leaving the track to avoid a collision, debris, or in response to a yellow flag "
        "is a justifiable reason and does not by itself produce a finding."
    ),
    "lasting_advantage": (
        "Where a driver gains a lasting time or positional advantage from a track-limits "
        "excursion, stewards weigh the counterfactual time gained against the ideal line at "
        "the entry speed actually carried; a negative gain (a mistake) is not exploitation."
    ),
    "unsafe_rejoin": (
        "Rejoining the track in a manner that endangers other drivers is assessed separately "
        "from the excursion itself, under the driving standards for unsafe rejoins."
    ),
}

_EVENT_TYPE_VALUES = [t.value for t in EventType]


@dataclass
class AgentContext:
    """Everything the agent's tools read from, assembled by the caller
    before a reasoning pass -- Tier 3 never fetches this itself.
    """

    config: EventConfig
    telemetry: dict[int, list[CarState]] = field(default_factory=dict)  # car_number -> states, time-sorted
    precedents: PrecedentStore | None = None


def build_tools(context: AgentContext) -> tuple[list[dict], dict[str, callable]]:
    """Returns (tool_schemas, dispatch) bound to one reasoning pass's context."""

    def get_telemetry(car: int, t0: float, t1: float) -> str:
        states = [s for s in context.telemetry.get(car, []) if t0 <= s.session_time <= t1]
        if not states:
            return f"No telemetry for car {car} in [{t0}, {t1}]."
        return "\n".join(
            f"t={s.session_time:.2f}s s={s.s:.1f}m d={s.d:+.2f}m speed={s.speed:.1f}m/s source={s.source}"
            for s in states
        )

    def get_neighbouring_cars(car: int, t0: float, t1: float) -> str:
        target = [s for s in context.telemetry.get(car, []) if t0 <= s.session_time <= t1]
        if not target:
            return f"No telemetry for car {car} in [{t0}, {t1}]."
        neighbours: set[int] = set()
        for other_car, states in context.telemetry.items():
            if other_car == car:
                continue
            for s in states:
                if not (t0 <= s.session_time <= t1):
                    continue
                nearest = min(target, key=lambda t: abs(t.session_time - s.session_time))
                if abs(nearest.s - s.s) < 20.0:  # within ~1-2 car lengths in arc length
                    neighbours.add(other_car)
                    break
        if not neighbours:
            return "No other cars within range in this window."
        return "Cars nearby: " + ", ".join(str(c) for c in sorted(neighbours))

    def get_session_precedents(corner: int, event_type: str) -> str:
        if context.precedents is None:
            return "No precedent store available for this session."
        matches = context.precedents.find_similar(corner=corner, event_type=EventType(event_type))
        if not matches:
            return "No precedents yet for this corner/event type this session."
        return "\n".join(f"{m.event_id}: corner {m.corner}, {m.event_type.value}, ruled {m.verdict.value}" for m in matches)

    def get_event_notes(circuit: str) -> str:
        c = context.config
        monitored = ", ".join(str(x) for x in sorted(c.monitored_corners))
        esc = c.escalation
        return (
            f"Circuit: {c.circuit} {c.year}. Monitored corners: [{monitored}]. "
            f"Minimum event duration: {c.min_event_duration_s * 1000:.0f}ms. "
            f"Escalation: black & white flag at strike {esc.black_and_white_flag_at}, "
            f"{esc.first_penalty_seconds}s penalty at strike {esc.first_penalty_at}, "
            f"{esc.second_penalty_seconds}s penalty at strike {esc.second_penalty_at}. "
            f"Citations: {', '.join(c.citations.values())}."
        )

    def get_driving_standards_guideline(topic: str) -> str:
        summary = _GUIDELINE_SUMMARIES.get(topic)
        if summary is None:
            return f"No local summary for topic {topic!r}. Known topics: {', '.join(_GUIDELINE_SUMMARIES)}."
        return f"[Local summary, not verbatim regulation text] {summary}"

    schemas = [
        {
            "name": "get_telemetry",
            "description": "Get this car's telemetry samples between t0 and t1 (session time, seconds).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "car": {"type": "integer", "description": "Car number."},
                    "t0": {"type": "number", "description": "Start of the time window, seconds."},
                    "t1": {"type": "number", "description": "End of the time window, seconds."},
                },
                "required": ["car", "t0", "t1"],
            },
        },
        {
            "name": "get_neighbouring_cars",
            "description": "Get which other cars were within about one car length of `car` between t0 and t1.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "car": {"type": "integer", "description": "Car number."},
                    "t0": {"type": "number", "description": "Start of the time window, seconds."},
                    "t1": {"type": "number", "description": "End of the time window, seconds."},
                },
                "required": ["car", "t0", "t1"],
            },
        },
        {
            "name": "get_session_precedents",
            "description": "Get how comparable events at this corner were ruled earlier this session.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "corner": {"type": "integer", "description": "Corner number."},
                    "event_type": {"type": "string", "enum": _EVENT_TYPE_VALUES},
                },
                "required": ["corner", "event_type"],
            },
        },
        {
            "name": "get_event_notes",
            "description": "Get this event weekend's monitored corners, escalation thresholds, and citations.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "circuit": {
                        "type": "string",
                        "description": "Circuit name (informational only; the active session's Event Notes are always returned).",
                    },
                },
                "required": ["circuit"],
            },
        },
        {
            "name": "get_driving_standards_guideline",
            "description": (
                "Get a local summary of the FIA Driving Standards Guidelines on one topic. "
                "Returns a paraphrase for this project, not verbatim regulatory text."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "enum": list(_GUIDELINE_SUMMARIES.keys()),
                    },
                },
                "required": ["topic"],
            },
        },
    ]

    dispatch = {
        "get_telemetry": get_telemetry,
        "get_neighbouring_cars": get_neighbouring_cars,
        "get_session_precedents": get_session_precedents,
        "get_event_notes": get_event_notes,
        "get_driving_standards_guideline": get_driving_standards_guideline,
    }

    return schemas, dispatch
