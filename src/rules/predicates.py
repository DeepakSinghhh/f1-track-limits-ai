"""Deterministic predicates for the Tier 2 rule engine (Section 5.6).

Apex Assist plan, Section 0 and Section 1: this module is plain Python.
No ML, no LLM, decides a regulatory question here — every branch is a
literal reading of Art. 33.3 and the FIA Driving Standards Guidelines,
and every function returns (bool, citation_string): what it decided and
the authority it decided it under.

The one exception is left_the_track's missing-data case, returning
(None, reason): with no wheel-contact reading there is no bool to render,
only an admission the predicate cannot be evaluated. Confidence-based
abstention on a present-but-marginal measurement is deliberately NOT done
here — that is the Tier 4 trust layer's job (measurement_margin, conformal
prediction over margin/sigma, Section 5.7), which does not exist in this
slice yet. Tier 2 stays purely deterministic: same point-estimate input,
same answer, every time.

Nothing here may reference a circuit name or a corner number: those are
Event Notes and belong in config/events/, loaded via src.config.
"""
from __future__ import annotations

from src.config import EventConfig
from src.rules.session_state import SessionState
from src.schemas import EventType, ExcursionEvent

#: FIA F1SR Art. 33.3: "A driver will be judged to have left the track if
#: no part of the car remains in contact with it" — i.e. all four wheels
#: beyond the outer edge of the white line. Two (or three) wheels off is
#: legal. This literal threshold is the only thing this module hardcodes;
#: it is the regulation itself, not an event parameter.
WHEELS_OFF_FOR_VIOLATION = 4


def left_the_track(event: ExcursionEvent, config: EventConfig) -> tuple[bool | None, str]:
    """FIA F1SR Art. 33.3 core test: all four contact patches beyond the
    outer edge of the white line, sustained past the minimum event
    duration gate — a excursion shorter than the gate is a measurement
    artefact (kerb strike, single-frame noise), not a track-limits event,
    and is rejected here rather than trusted to an upstream classifier.
    """
    citation = config.citations["core_rule"]

    if event.wheels_off_peak is None:
        return None, f"{citation}: wheel-contact data unavailable at peak excursion"

    if event.duration_s < config.min_event_duration_s:
        return (
            False,
            f"{citation}: excursion lasted {event.duration_s * 1000:.0f}ms, below the "
            f"{config.min_event_duration_s * 1000:.0f}ms minimum duration gate — treated "
            f"as a measurement artefact, not evaluated as a track-limits event",
        )

    if event.wheels_off_peak >= WHEELS_OFF_FOR_VIOLATION:
        return (
            True,
            f"{citation}: all four wheels beyond the outer edge of the white line for "
            f"{event.duration_s * 1000:.0f}ms, peak margin {event.max_margin_m * 100:.1f}cm",
        )

    return (
        False,
        f"{citation}: {event.wheels_off_peak}/4 wheels beyond the track edge at peak — not all four",
    )


def corner_is_monitored(corner: int, config: EventConfig) -> tuple[bool, str]:
    if corner in config.monitored_corners:
        return True, f"corner {corner} is in this event's monitored-corners list (Event Notes)"
    return False, f"corner {corner} is not in this event's monitored-corners list (Event Notes)"


def exception_forced_off(event: ExcursionEvent) -> tuple[bool, str]:
    applies = event.proposed_type == EventType.FORCED_OFF
    citation = "FIA Driving Standards Guidelines: forced off the track by another car"
    return applies, citation if applies else f"not applicable: proposed_type={event.proposed_type.value}"


def exception_justifiable_reason(event: ExcursionEvent) -> tuple[bool, str]:
    applies = event.proposed_type == EventType.AVOIDANCE
    citation = "FIA Driving Standards Guidelines: justifiable reason (avoidance, debris, yellow flag)"
    return applies, citation if applies else f"not applicable: proposed_type={event.proposed_type.value}"


def exception_part_of_penalised_incident(
    event: ExcursionEvent, session_state: SessionState
) -> tuple[bool, str]:
    applies = session_state.is_penalized(event.event_id)
    citation = "FIA Driving Standards Guidelines: already penalised as part of a separate incident"
    return applies, citation if applies else "no separate penalised incident on record for this event"
