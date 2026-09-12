import pytest

from src.geofence import ZoneCrossingTracker
from src.schemas import EventType


def test_no_event_while_never_violating():
    tracker = ZoneCrossingTracker(fps=10, min_duration_s=0.150)
    for frame_id in range(1, 11):
        assert tracker.update(False, frame_id) is None


def test_no_event_while_still_in_progress():
    tracker = ZoneCrossingTracker(fps=10, min_duration_s=0.150)
    assert tracker.update(True, 1) is None
    assert tracker.update(True, 2) is None
    assert tracker.update(True, 3) is None


def test_event_produced_on_transition_back_to_false():
    tracker = ZoneCrossingTracker(fps=10, min_duration_s=0.150)
    tracker.update(True, 5)   # onset at frame 5 -> t=0.5s
    tracker.update(True, 6)
    tracker.update(True, 12)  # still elevated
    event = tracker.update(False, 13)  # reentry at frame 13 -> t=1.3s

    assert event is not None
    assert event.t_onset == pytest.approx(0.5)
    assert event.t_reentry == pytest.approx(1.3)
    assert event.duration_s == pytest.approx(0.8)


def test_short_excursion_is_a_measurement_artefact():
    tracker = ZoneCrossingTracker(fps=10, min_duration_s=0.150)
    tracker.update(True, 5)
    event = tracker.update(False, 6)  # 1 frame = 100ms, below the 150ms gate
    assert event.proposed_type == EventType.MEASUREMENT_ARTEFACT


def test_sustained_excursion_is_not_an_artefact():
    tracker = ZoneCrossingTracker(fps=10, min_duration_s=0.150)
    tracker.update(True, 5)
    event = tracker.update(False, 8)  # 300ms
    assert event.proposed_type == EventType.EXCURSION_NO_ADVANTAGE


def test_wheels_off_peak_and_margin_are_honestly_unmeasured():
    tracker = ZoneCrossingTracker(fps=10, min_duration_s=0.150)
    tracker.update(True, 5)
    event = tracker.update(False, 8)
    assert event.wheels_off_peak is None
    assert event.max_margin_m == 0.0
    assert event.margin_sigma_m == 0.0


def test_close_finalizes_a_still_open_excursion():
    tracker = ZoneCrossingTracker(fps=10, min_duration_s=0.150)
    tracker.update(True, 5)
    event = tracker.close(10)  # stream ends while still in the excursion
    assert event is not None
    assert event.t_onset == pytest.approx(0.5)
    assert event.t_reentry == pytest.approx(1.0)


def test_close_is_a_noop_when_not_in_an_excursion():
    tracker = ZoneCrossingTracker(fps=10, min_duration_s=0.150)
    assert tracker.close(10) is None

    # also a no-op right after a crossing has already been closed normally
    tracker.update(True, 1)
    tracker.update(False, 2)
    assert tracker.close(10) is None


def test_car_number_is_the_caller_supplied_placeholder():
    tracker = ZoneCrossingTracker(fps=10, min_duration_s=0.150, car_number=7)
    tracker.update(True, 1)
    event = tracker.update(False, 5)
    assert event.car_number == 7
    assert event.relational.car_number == 7


def test_corner_and_lap_are_the_documented_demo_placeholders():
    tracker = ZoneCrossingTracker(fps=10, min_duration_s=0.150)
    tracker.update(True, 1)
    event = tracker.update(False, 5)
    assert event.corner == 0
    assert event.lap == 0
