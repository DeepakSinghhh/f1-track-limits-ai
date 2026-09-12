import numpy as np
import pytest

from src.render.incident import build_incident_annotations
from src.schemas import CarState
from src.track.frame import TrackFrame
from tests.factories import make_event

# Straight segment (0,0) -> (10,0): to_cartesian(s, d) == (s, d) for
# s in [0, 10], matching the fixture other src/vision/ tests use.
CENTRELINE = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
FPS = 30.0


def make_state(session_time, s=5.0, d=0.0):
    return CarState(
        car_number=44,
        session_time=session_time,
        s=s,
        d=d,
        heading=0.0,
        speed=60.0,
        yaw_rate=0.0,
        wheel_d=None,
        wheel_sigma=None,
        source="vision",
        reproj_error_px=1.0,
        occlusion_frac=0.0,
        n_sensors=1,
    )


def test_only_states_within_the_event_window_are_included():
    event = make_event()  # t_onset=100.0, t_max_excursion=100.3, t_reentry=100.9
    states = [make_state(99.0), make_state(100.3), make_state(100.9), make_state(101.5)]
    track_frame = TrackFrame(CENTRELINE)

    result = build_incident_annotations(states, event, track_frame, heading_rad=0.0, fps=FPS)

    assert len(result) == 2
    assert [ann.session_time for _, ann in result] == [100.3, 100.9]


def test_frame_id_is_recovered_from_session_time_and_fps():
    event = make_event()
    # frame_id 3009 at 30fps -> session_time 100.3, exactly inside the window
    state = make_state(session_time=3009 / FPS)
    track_frame = TrackFrame(CENTRELINE)

    [(frame_id, _)] = build_incident_annotations([state], event, track_frame, heading_rad=0.0, fps=FPS)

    assert frame_id == 3009


def test_contact_points_are_four_distinct_wheel_positions_not_a_centroid():
    event = make_event()
    state = make_state(session_time=100.3, s=5.0, d=0.0)
    track_frame = TrackFrame(CENTRELINE)

    [(_, annotation)] = build_incident_annotations([state], event, track_frame, heading_rad=0.0, fps=FPS)

    assert len(annotation.contact_points_xy) == 4
    assert len(set(annotation.contact_points_xy)) == 4


def test_empty_when_no_states_fall_in_the_event_window():
    event = make_event()
    states = [make_state(0.0), make_state(500.0)]
    track_frame = TrackFrame(CENTRELINE)

    result = build_incident_annotations(states, event, track_frame, heading_rad=0.0, fps=FPS)

    assert result == []


def test_empty_states_list_returns_empty():
    event = make_event()
    track_frame = TrackFrame(CENTRELINE)
    assert build_incident_annotations([], event, track_frame, heading_rad=0.0, fps=FPS) == []
