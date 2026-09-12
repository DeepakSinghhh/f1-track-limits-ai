"""Glue between a live pipeline run and Section 5.9's clip export
(render_incident_clip): turns the CarStates a run already captured into
the FrameAnnotations that function needs, paired with the frame_id each
one came from so a caller holding raw video frames (app.py) can look up
the matching image.

CarState only carries session_time, not the frame_id it was built from
-- car_state_from_reference_point derives session_time as frame_id / fps,
so recovering frame_id here is an exact round-trip (up to floating point),
not a guess.
"""
from __future__ import annotations

from src.render.overlay import FrameAnnotation
from src.schemas import CarState, ExcursionEvent
from src.track.frame import TrackFrame
from src.vision.contact import wheel_world_positions


def build_incident_annotations(
    states: list[CarState],
    event: ExcursionEvent,
    track_frame: TrackFrame,
    heading_rad: float,
    fps: float,
) -> list[tuple[int, FrameAnnotation]]:
    """Returns (frame_id, FrameAnnotation) pairs, in order, for every
    state whose session_time falls within [event.t_onset, event.t_reentry].
    Empty if no captured state falls in that window (e.g. the event was
    localised from a gap in detections that never itself produced a
    state) -- callers should treat that as "no clip for this event"
    rather than an error.
    """
    result = []
    for state in states:
        if not (event.t_onset <= state.session_time <= event.t_reentry):
            continue
        car_xy = track_frame.to_cartesian(state.s, state.d)
        wheels_xy = wheel_world_positions(car_xy, heading_rad)
        frame_id = round(state.session_time * fps)
        annotation = FrameAnnotation(session_time=state.session_time, contact_points_xy=list(wheels_xy))
        result.append((frame_id, annotation))
    return result
