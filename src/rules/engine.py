"""Tier 2: deterministic rule engine. candidates -> regulatory findings.

Apex Assist plan, Section 0: sanction selection is a human function. This
engine never issues a penalty — it produces a Finding (a fact plus the
applicable regulation) and a Verdict (which may be INSUFFICIENT_EVIDENCE
when the underlying measurement is missing — a first-class result, not a
failure). Nothing here decides what happens to the driver; see
src.rules.escalation for the strike/consequence layer, which only advances
on explicit steward confirmation.
"""
from __future__ import annotations

from src.config import EventConfig
from src.rules.predicates import (
    corner_is_monitored,
    exception_forced_off,
    exception_justifiable_reason,
    exception_part_of_penalised_incident,
    left_the_track,
)
from src.rules.session_state import SessionState
from src.schemas import ExcursionEvent, Finding, Verdict


def _format_session_time(t_seconds: float) -> str:
    minutes, seconds = divmod(max(t_seconds, 0.0), 60)
    return f"{int(minutes):02d}:{seconds:06.3f}"


class RuleEngine:
    """Applies one EventConfig's Event Notes to ExcursionEvents.

    One instance per event weekend. Stateless across calls: the same
    ExcursionEvent (and session_state) always produces the same
    (Finding, Verdict) pair, which is what "deterministic" means here.
    """

    def __init__(self, config: EventConfig):
        self.config = config

    def evaluate(
        self,
        event: ExcursionEvent,
        session_state: SessionState | None = None,
    ) -> tuple[Finding, Verdict]:
        """Evaluate one candidate excursion against this event's rules."""
        session_state = session_state or SessionState()

        monitored, monitored_reason = corner_is_monitored(event.corner, self.config)
        forced_off, forced_off_reason = exception_forced_off(event)
        avoidance, avoidance_reason = exception_justifiable_reason(event)
        already_penalized, already_penalized_reason = exception_part_of_penalised_incident(
            event, session_state
        )

        exceptions_evaluated = {
            "forced_off": forced_off,
            "avoidance": avoidance,
            "already_penalized": already_penalized,
            "corner_not_monitored": not monitored,
        }

        core_result, core_reason = left_the_track(event, self.config)

        if core_result is None:
            verdict = Verdict.INSUFFICIENT_EVIDENCE
            description = core_reason
        elif core_result is False:
            verdict = Verdict.NO_VIOLATION
            description = core_reason
        elif any(exceptions_evaluated.values()):
            # Geometrically a violation, but an exception excuses it — the
            # exception reasons, not the geometry, are what a steward
            # needs to see here.
            verdict = Verdict.NO_VIOLATION
            reasons = [
                r
                for applies, r in (
                    (forced_off, forced_off_reason),
                    (avoidance, avoidance_reason),
                    (already_penalized, already_penalized_reason),
                    (not monitored, monitored_reason),
                )
                if applies
            ]
            description = "excused — " + "; ".join(reasons)
        else:
            verdict = Verdict.VIOLATION
            description = core_reason

        authority = [c for c in self.config.citations.values() if c]

        finding = Finding(
            event_id=event.event_id,
            car_number=event.car_number,
            lap=event.lap,
            corner=event.corner,
            session_time=_format_session_time(event.t_max_excursion),
            violation=verdict == Verdict.VIOLATION,
            description=description,
            min_margin_cm=event.max_margin_m * 100,
            margin_uncertainty_cm=event.margin_sigma_m * 100,
            authority=authority,
            exceptions_evaluated=exceptions_evaluated,
            strike_context="pending steward confirmation",
            corner_monitored=monitored,
        )
        return finding, verdict
