"""Deterministic predicates for the Tier 2 rule engine.

Apex Assist plan, Section 0 and Section 1: this module is plain Python.
No ML, no LLM, decides a regulatory question here — every branch is a
literal reading of Art. 33.3 and the FIA Driving Standards Guidelines,
and every output states which fact it is asserting and why.

Nothing here may reference a circuit name or a corner number: those are
Event Notes and belong in config/events/, loaded via src.config.
"""
from __future__ import annotations

from src.schemas import EventType, ExcursionEvent, Verdict

#: FIA F1SR Art. 33.3: "A driver will be judged to have left the track if
#: no part of the car remains in contact with it" — i.e. all four wheels
#: beyond the outer edge of the white line. Two (or three) wheels off is
#: legal. This literal threshold is the only thing this module hardcodes;
#: it is the regulation itself, not an event parameter.
WHEELS_OFF_FOR_VIOLATION = 4


def evaluate_core_test(event: ExcursionEvent, min_confidence_sigma: float) -> tuple[Verdict, str]:
    """FIA F1SR Art. 33.3 core test, applied to one excursion's peak measurement.

    Returns (Verdict, human-readable reason). INSUFFICIENT_EVIDENCE is
    returned — not guessed past — when the wheel-contact reading is
    missing, or when the peak margin is not resolvable from the boundary
    within min_confidence_sigma measurement-sigma (a deterministic
    statistical test on the reported uncertainty, not a model confidence
    score).
    """
    if event.wheels_off_peak is None:
        return (
            Verdict.INSUFFICIENT_EVIDENCE,
            "wheel-contact data unavailable at peak excursion; cannot apply Art. 33.3",
        )

    if event.margin_sigma_m > 0:
        z = event.max_margin_m / event.margin_sigma_m
    else:
        z = float("inf") if event.max_margin_m != 0 else 0.0

    if event.wheels_off_peak >= WHEELS_OFF_FOR_VIOLATION:
        if z < min_confidence_sigma:
            return (
                Verdict.INSUFFICIENT_EVIDENCE,
                f"all four wheels reported beyond the track edge, but peak margin "
                f"{event.max_margin_m * 100:.1f}cm is within {z:.2f}σ of the boundary "
                f"(threshold {min_confidence_sigma:.1f}σ) — not distinguishable from zero",
            )
        return (
            Verdict.VIOLATION,
            f"all four wheels beyond the track edge for {event.duration_s * 1000:.0f}ms, "
            f"peak margin {event.max_margin_m * 100:.1f}cm ({z:.2f}σ)",
        )

    return (
        Verdict.NO_VIOLATION,
        f"{event.wheels_off_peak}/4 wheels beyond the track edge at peak — not all four",
    )


def evaluate_exceptions(
    event: ExcursionEvent,
    corner_monitored: bool,
    already_penalized: bool,
) -> dict[str, bool]:
    """Evaluate every FIA Driving Standards Guidelines exception explicitly.

    All four keys are always present, whichever way they resolve — a
    non-applicable exception is recorded as False, never omitted, per the
    plan's requirement that "Exceptions evaluated: forced_off=false,
    avoidance=false" is required output, not optional.
    """
    return {
        "forced_off": event.proposed_type == EventType.FORCED_OFF,
        "avoidance": event.proposed_type == EventType.AVOIDANCE,
        "already_penalized": already_penalized,
        "corner_not_monitored": not corner_monitored,
    }


def exception_applies(exceptions_evaluated: dict[str, bool]) -> bool:
    return any(exceptions_evaluated.values())


def describe_exception(exceptions_evaluated: dict[str, bool]) -> str:
    reasons = [name for name, applies in exceptions_evaluated.items() if applies]
    return "excused: " + ", ".join(reasons)
