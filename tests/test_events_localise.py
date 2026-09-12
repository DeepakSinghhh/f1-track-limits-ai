import numpy as np
import pytest

from src.events.localise import localise_events
from src.schemas import CarState, EventType, RelationalContext
from src.track.boundary import Boundary


def make_flat_boundary(half_width=4.0, total_length=1000.0):
    s_samples = np.linspace(0, total_length, 20, endpoint=False)
    left = np.full(20, half_width)
    right = np.full(20, half_width)
    return Boundary(s_samples, left, right, white_line_width_m=0.0, total_length=total_length)


def make_state(car_number, t, s, d, wheel_d=None, wheel_sigma=None):
    return CarState(
        car_number=car_number,
        session_time=t,
        s=s,
        d=d,
        heading=0.0,
        speed=60.0,
        yaw_rate=0.0,
        wheel_d=wheel_d,
        wheel_sigma=wheel_sigma,
        source="telemetry",
        reproj_error_px=None,
        occlusion_frac=0.0,
        n_sensors=1,
    )


def make_stream(d_profile, dt=0.1, wheel_spread=None):
    states = []
    for i, d in enumerate(d_profile):
        t = round(i * dt, 6)
        wheel_d = None
        if wheel_spread is not None:
            wheel_d = (d + wheel_spread, d + wheel_spread, d - wheel_spread, d - wheel_spread)
        states.append(make_state(car_number=44, t=t, s=float(i * 10), d=d, wheel_d=wheel_d))
    return states


def CONSTANT_CORNER(s):
    return 1


def CONSTANT_LAP(t):
    return 5


def test_sustained_excursion_produces_one_event_with_correct_timing():
    boundary = make_flat_boundary(half_width=4.0)
    # inside (d=3.0) -> off (d=4.5) for 700ms -> back inside
    d_profile = [3.0] * 5 + [4.5] * 7 + [3.0] * 8
    states = make_stream(d_profile)

    events = localise_events(states, boundary, CONSTANT_CORNER, CONSTANT_LAP)

    assert len(events) == 1
    event = events[0]
    assert event.car_number == 44
    assert event.corner == 1
    assert event.lap == 5
    assert event.t_onset == pytest.approx(0.5)
    assert event.t_reentry == pytest.approx(1.2)
    assert event.duration_s == pytest.approx(0.7)
    assert event.max_margin_m == pytest.approx(0.5)
    assert event.proposed_type == EventType.EXCURSION_NO_ADVANTAGE


def test_short_excursion_is_flagged_as_measurement_artefact():
    boundary = make_flat_boundary(half_width=4.0)
    # a single 100ms blip: on at t=0.5, back inside at t=0.6
    d_profile = [3.0] * 5 + [4.5] + [3.0] * 8
    states = make_stream(d_profile)

    events = localise_events(states, boundary, CONSTANT_CORNER, CONSTANT_LAP)

    assert len(events) == 1
    assert events[0].duration_s < 0.150
    assert events[0].proposed_type == EventType.MEASUREMENT_ARTEFACT


def test_wheels_off_peak_is_none_without_wheel_data():
    boundary = make_flat_boundary(half_width=4.0)
    d_profile = [3.0] * 5 + [4.5] * 7 + [3.0] * 8
    states = make_stream(d_profile)  # no wheel_spread -> wheel_d is None

    events = localise_events(states, boundary, CONSTANT_CORNER, CONSTANT_LAP)
    assert events[0].wheels_off_peak is None


def test_wheels_off_peak_counts_from_wheel_data_when_available():
    boundary = make_flat_boundary(half_width=4.0)
    d_profile = [3.0] * 5 + [4.5] * 7 + [3.0] * 8
    # spread of 0.3m either side of centre-d, well within the excursion margin
    states = make_stream(d_profile, wheel_spread=0.3)

    events = localise_events(states, boundary, CONSTANT_CORNER, CONSTANT_LAP)
    assert events[0].wheels_off_peak == 4


def test_two_wheels_off_is_still_a_candidate_with_wheels_off_peak_below_four():
    boundary = make_flat_boundary(half_width=4.0)
    # centre-d only just past the edge (4.05); a 0.5m wheel spread means
    # only the outer pair (d + 0.5 = 4.55) clears the edge, not the inner
    # pair (d - 0.5 = 3.55) -- 2 wheels off, not 4.
    d_profile = [3.0] * 5 + [4.05] * 7 + [3.0] * 8
    states = make_stream(d_profile, wheel_spread=0.5)

    events = localise_events(states, boundary, CONSTANT_CORNER, CONSTANT_LAP)
    assert len(events) == 1
    assert events[0].wheels_off_peak == 2


def test_no_excursion_stays_below_threshold_the_whole_time():
    boundary = make_flat_boundary(half_width=4.0)
    d_profile = [2.0] * 20
    states = make_stream(d_profile)
    assert localise_events(states, boundary, CONSTANT_CORNER, CONSTANT_LAP) == []


def test_excursion_still_open_at_stream_end_is_still_reported():
    boundary = make_flat_boundary(half_width=4.0)
    d_profile = [3.0] * 5 + [4.5] * 7  # never comes back inside before the stream ends
    states = make_stream(d_profile)

    events = localise_events(states, boundary, CONSTANT_CORNER, CONSTANT_LAP)
    assert len(events) == 1
    assert events[0].t_reentry == states[-1].session_time


def test_forced_off_proposed_when_car_alongside_at_peak():
    boundary = make_flat_boundary(half_width=4.0)
    d_profile = [3.0] * 5 + [4.5] * 7 + [3.0] * 8
    states = make_stream(d_profile)
    # Mark "alongside" for the whole elevated segment so the assertion
    # doesn't depend on exactly which sample the peak tie-break lands on.
    relational = {
        s.session_time: RelationalContext(
            car_number=44,
            session_time=s.session_time,
            alongside=[7] if s.d == 4.5 else [],
            nearest_delta_s=1.0,
            nearest_delta_d=1.0,
            yellow_flag_sector=False,
        )
        for s in states
    }

    events = localise_events(states, boundary, CONSTANT_CORNER, CONSTANT_LAP, relational=relational)
    assert events[0].proposed_type == EventType.FORCED_OFF


def test_margin_sigma_defaults_when_no_wheel_sigma_present():
    boundary = make_flat_boundary(half_width=4.0)
    d_profile = [3.0] * 5 + [4.5] * 7 + [3.0] * 8
    states = make_stream(d_profile)
    events = localise_events(states, boundary, CONSTANT_CORNER, CONSTANT_LAP)
    assert events[0].margin_sigma_m == pytest.approx(0.20)
