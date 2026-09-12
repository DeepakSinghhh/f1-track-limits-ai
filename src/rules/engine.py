"""Tier 2: deterministic rule engine. candidates -> regulatory findings.

Apex Assist plan, Section 0: sanction selection is a human function. This
engine never issues a penalty — it produces a Finding (a fact plus the
applicable regulation) and a Verdict (which may be INSUFFICIENT_EVIDENCE,
a first-class result, not a failure). Nothing here decides what happens to
the driver; see src.rules.escalation for the strike/consequence layer,
which only advances on explicit steward confirmation.
"""
from __future__ import annotations

from src.config import EventConfig
from src.rules.predicates import (
    describe_exception,
    evaluate_core_test,
    evaluate_exceptions,
    exception_applies,
)
from src.schemas import ExcursionEvent, Finding, Verdict


def _format_session_time(t_seconds: float) -> str:
    minutes, seconds = divmod(max(t_seconds, 0.0), 60)
    return f"{int(minutes):02d}:{seconds:06.3f}"


class RuleEngine:
    """Applies one EventConfig's Event Notes to ExcursionEvents.

    One instance per event weekend. Stateless across calls: the same
    ExcursionEvent always produces the same (Finding, Verdict) pair, which
    is what "deterministic" means here.
    """

    def __init__(self, config: EventConfig):
        self.config = config

    def evaluate(
        self,
        event: ExcursionEvent,
        already_penalized: bool = False,
    ) -> tuple[Finding, Verdict]:
        """Evaluate one candidate excursion against this event's rules.

        already_penalized: caller-supplied fact (from the incident record,
        not derivable from the event alone) that this excursion is part of
        a separate incident already penalised on other grounds
        (Section 1.2, exception 3).
        """
        corner_monitored = event.corner in self.config.monitored_corners

        exceptions_evaluated = evaluate_exceptions(
            event, corner_monitored=corner_monitored, already_penalized=already_penalized
        )

        if exception_applies(exceptions_evaluated):
            verdict = Verdict.NO_VIOLATION
            description = describe_exception(exceptions_evaluated)
        else:
            verdict, description = evaluate_core_test(event, self.config.min_confidence_sigma)

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
            corner_monitored=corner_monitored,
        )
        return finding, verdict
