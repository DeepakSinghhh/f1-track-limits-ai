"""Synthetic Tier 1 instances for exercising the rule engine in isolation."""
from src.schemas import EventType, ExcursionEvent, RelationalContext


def make_relational(car_number: int = 44) -> RelationalContext:
    return RelationalContext(
        car_number=car_number,
        session_time=0.0,
        alongside=[],
        nearest_delta_s=999.0,
        nearest_delta_d=999.0,
        yellow_flag_sector=False,
    )


def make_event(
    *,
    event_id: str = "evt-1",
    car_number: int = 44,
    lap: int = 12,
    corner: int = 1,
    wheels_off_peak: int | None = 4,
    max_margin_m: float = 0.30,
    margin_sigma_m: float = 0.02,
    duration_s: float = 0.62,
    proposed_type: EventType = EventType.EXCURSION_NO_ADVANTAGE,
) -> ExcursionEvent:
    return ExcursionEvent(
        event_id=event_id,
        car_number=car_number,
        lap=lap,
        corner=corner,
        t_onset=100.0,
        t_max_excursion=100.3,
        t_reentry=100.9,
        max_margin_m=max_margin_m,
        margin_sigma_m=margin_sigma_m,
        duration_s=duration_s,
        wheels_off_peak=wheels_off_peak,
        proposed_type=proposed_type,
        relational=make_relational(car_number),
    )
