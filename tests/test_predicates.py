from src.config import load_event_config
from src.rules.predicates import (
    corner_is_monitored,
    exception_forced_off,
    exception_justifiable_reason,
    exception_part_of_penalised_incident,
    left_the_track,
)
from src.rules.session_state import SessionState
from src.schemas import EventType
from tests.factories import make_event

CONFIG_PATH = "config/events/red_bull_ring_2023.yaml"


def config():
    return load_event_config(CONFIG_PATH)


def test_four_wheels_off_with_full_duration_is_a_violation():
    event = make_event(wheels_off_peak=4, duration_s=0.62)
    result, reason = left_the_track(event, config())
    assert result is True
    assert "all four wheels" in reason


def test_two_wheels_off_is_not_a_violation():
    event = make_event(wheels_off_peak=2, duration_s=0.62)
    result, _ = left_the_track(event, config())
    assert result is False


def test_three_wheels_off_is_not_a_violation():
    event = make_event(wheels_off_peak=3, duration_s=0.62)
    result, _ = left_the_track(event, config())
    assert result is False


def test_short_excursion_is_a_measurement_artefact_not_a_violation():
    # below the 150ms minimum duration gate configured for this event
    event = make_event(wheels_off_peak=4, duration_s=0.10)
    result, reason = left_the_track(event, config())
    assert result is False
    assert "artefact" in reason


def test_missing_wheel_data_cannot_be_evaluated():
    event = make_event(wheels_off_peak=None)
    result, reason = left_the_track(event, config())
    assert result is None
    assert "unavailable" in reason


def test_corner_is_monitored():
    assert corner_is_monitored(1, config())[0] is True   # in red_bull_ring_2023's list
    assert corner_is_monitored(2, config())[0] is False  # not in the list


def test_forced_off_exception():
    forced = make_event(proposed_type=EventType.FORCED_OFF)
    clean = make_event(proposed_type=EventType.EXCURSION_NO_ADVANTAGE)
    assert exception_forced_off(forced)[0] is True
    assert exception_forced_off(clean)[0] is False


def test_justifiable_reason_exception():
    avoidance = make_event(proposed_type=EventType.AVOIDANCE)
    clean = make_event(proposed_type=EventType.EXCURSION_NO_ADVANTAGE)
    assert exception_justifiable_reason(avoidance)[0] is True
    assert exception_justifiable_reason(clean)[0] is False


def test_already_penalised_exception_reads_session_state():
    event = make_event(event_id="evt-42")
    empty_state = SessionState()
    penalized_state = SessionState(penalized_event_ids=frozenset({"evt-42"}))
    assert exception_part_of_penalised_incident(event, empty_state)[0] is False
    assert exception_part_of_penalised_incident(event, penalized_state)[0] is True
