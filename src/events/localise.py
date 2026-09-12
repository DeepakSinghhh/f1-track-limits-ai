"""Tier 1: event localisation. state stream -> candidate excursion events.

Section 5.4: "A violation is not a frame property. It is an event with
onset, peak and re-entry. Frame-level classification produces flicker and
false positives on kerb strikes." This module does not train anything —
hysteresis plus a minimum duration gate is the defensible, debuggable,
fast approach for this build (Section 8 rules out frame-level violation
classification and training a model from scratch). A temporal
convolutional network over the CarState sequence is the natural upgrade
once there is enough labelled data to justify training one.
"""
from __future__ import annotations

import uuid
from typing import Callable

from src.schemas import CarState, EventType, ExcursionEvent, RelationalContext
from src.track.boundary import Boundary

#: Hysteresis band around the boundary (Section 5.4): enter the excursion
#: state past +2cm, exit past -2cm. Prevents chatter right at the edge.
ENTER_MARGIN_M = 0.02
EXIT_MARGIN_M = -0.02

#: Telemetry cannot resolve individual wheels (Section 5.2); this is the
#: fallback margin_sigma_m used when a CarState carries no wheel_sigma.
DEFAULT_MARGIN_SIGMA_M = 0.20


def localise_events(
    states: list[CarState],
    boundary: Boundary,
    corner_of: Callable[[float], int],
    lap_of: Callable[[float], int],
    relational: dict[float, RelationalContext] | None = None,
    min_duration_s: float = 0.150,
) -> list[ExcursionEvent]:
    """states: one car's CarState stream, in increasing session_time order.

    corner_of / lap_of: map an arc-length s (corner) or session_time (lap)
    to the Event Notes' corner numbering / lap count — a telemetry/
    reference.py concern, supplied by the caller rather than guessed here.
    relational: optional map of session_time -> RelationalContext for a
    sample; a neutral default (no cars alongside, no yellow) is used for
    any sample not present.
    """
    relational = relational or {}
    events: list[ExcursionEvent] = []

    in_excursion = False
    onset_idx: int | None = None
    peak_idx: int | None = None
    peak_margin = -float("inf")

    for i, state in enumerate(states):
        car_margin = _car_margin(state, boundary)

        if not in_excursion:
            if car_margin > ENTER_MARGIN_M:
                in_excursion = True
                onset_idx = i
                peak_idx = i
                peak_margin = car_margin
            continue

        if car_margin > peak_margin:
            peak_margin = car_margin
            peak_idx = i

        if car_margin < EXIT_MARGIN_M:
            events.append(
                _build_event(states, onset_idx, peak_idx, i, boundary, corner_of, lap_of, relational, min_duration_s)
            )
            in_excursion = False
            onset_idx = peak_idx = None
            peak_margin = -float("inf")

    if in_excursion:
        # Excursion still open when the stream ends (e.g. end of session) —
        # close it at the last sample rather than dropping it.
        events.append(
            _build_event(
                states, onset_idx, peak_idx, len(states) - 1, boundary, corner_of, lap_of, relational, min_duration_s
            )
        )

    return events


def _car_margin(state: CarState, boundary: Boundary) -> float:
    """The signal that governs hysteresis entry/exit is the CAR's own
    (centre) margin, not a per-wheel one. Section 5.2: telemetry — the
    branch covering every car at every corner — has no per-wheel data at
    all (wheel_d is None), so candidate detection has to work from the
    car's own track position; wheels_off_peak (the Art. 33.3 fact) is
    recorded separately, only where wheel data actually exists. This also
    matches the funnel in Section 2: far more candidates than actual
    four-wheel violations, because most excursions are legal (1-3 wheels).
    """
    return boundary.signed_distance_to_edge(state.s, state.d)


def _wheels_off(state: CarState, boundary: Boundary) -> int | None:
    if state.wheel_d is None:
        return None
    margins = [boundary.signed_distance_to_edge(state.s, wd) for wd in state.wheel_d]
    return sum(1 for m in margins if m > 0)


def _build_event(
    states: list[CarState],
    onset_idx: int,
    peak_idx: int,
    reentry_idx: int,
    boundary: Boundary,
    corner_of: Callable[[float], int],
    lap_of: Callable[[float], int],
    relational: dict[float, RelationalContext],
    min_duration_s: float,
) -> ExcursionEvent:
    onset = states[onset_idx]
    peak = states[peak_idx]
    reentry = states[reentry_idx]

    max_margin_m = max(_car_margin(peak, boundary), 0.0)
    wheels_off_peak = _wheels_off(peak, boundary)

    if peak.wheel_sigma is not None:
        margin_sigma_m = max(peak.wheel_sigma)
    else:
        margin_sigma_m = DEFAULT_MARGIN_SIGMA_M

    duration_s = reentry.session_time - onset.session_time

    context = relational.get(peak.session_time) or RelationalContext(
        car_number=peak.car_number,
        session_time=peak.session_time,
        alongside=[],
        nearest_delta_s=float("inf"),
        nearest_delta_d=float("inf"),
        yellow_flag_sector=False,
    )

    proposed_type = _propose_type(duration_s, min_duration_s, context)

    return ExcursionEvent(
        event_id=str(uuid.uuid4()),
        car_number=onset.car_number,
        lap=lap_of(onset.session_time),
        corner=corner_of(peak.s),
        t_onset=onset.session_time,
        t_max_excursion=peak.session_time,
        t_reentry=reentry.session_time,
        max_margin_m=max_margin_m,
        margin_sigma_m=margin_sigma_m,
        duration_s=duration_s,
        wheels_off_peak=wheels_off_peak,
        proposed_type=proposed_type,
        relational=context,
    )


def _propose_type(duration_s: float, min_duration_s: float, context: RelationalContext) -> EventType:
    """Section 5.4: propose FORCED_OFF when a car was alongside on the
    excursion side during the approach, AVOIDANCE under yellow (or a
    decelerating car ahead — not modelled here without a leader signal),
    otherwise EXCURSION_NO_ADVANTAGE by default. The counterfactual-gain
    split against EXCURSION_WITH_GAIN is Section 5.5's job (the lasting-
    advantage estimator), not localisation.
    """
    if duration_s < min_duration_s:
        return EventType.MEASUREMENT_ARTEFACT
    if context.alongside:
        return EventType.FORCED_OFF
    if context.yellow_flag_sector:
        return EventType.AVOIDANCE
    return EventType.EXCURSION_NO_ADVANTAGE
