"""Tests for the calibrated path added to TrackLimitDetector. Exercises
only the pure geometry (car_state_from_reference_point, finalize) and the
constructor's validation -- never touches YOLO/ultralytics, matching how
this module now lazy-loads the model.
"""
import math

import pytest

from src.calibration import calibrate
from src.config import load_event_config
from src.detector import TrackLimitDetector
from src.schemas import Verdict
from src.track.build import build_straight_segment_track

CONFIG_PATH = "config/events/demo_clip.yaml"


def make_calibration():
    # world = 0.1 * pixel (metres per pixel), no rotation/perspective -- easy to reason about by hand
    image_points = [(0, 0), (1000, 0), (1000, 800), (0, 800)]
    world_points = [(x * 0.1, y * 0.1) for x, y in image_points]
    return calibrate(image_points, world_points)


def make_track():
    # a straight segment along world +x, from (0,0) to (100,0), 4m either side
    return build_straight_segment_track(
        p1=(0.0, 0.0), p2=(100.0, 0.0), left_half_width_m=4.0, right_half_width_m=4.0, white_line_width_m=0.10
    )


def make_detector(fps=10.0, **overrides):
    calibration = overrides.pop("calibration", make_calibration())
    track_frame, boundary = overrides.pop("track", make_track())
    kwargs = dict(
        fps=fps,
        config=CONFIG_PATH,
        calibration=calibration,
        track_frame=track_frame,
        boundary=boundary,
        heading_rad=0.0,  # travelling along +x, matching the track segment's direction
        corner=0,
    )
    kwargs.update(overrides)
    return TrackLimitDetector(**kwargs)


def test_constructor_requires_full_calibration_bundle():
    calibration = make_calibration()
    track_frame, boundary = make_track()
    with pytest.raises(ValueError):
        TrackLimitDetector(fps=10.0, config=CONFIG_PATH, calibration=calibration)  # missing track_frame/boundary/heading
    with pytest.raises(ValueError):
        TrackLimitDetector(fps=10.0, config=CONFIG_PATH, calibration=calibration, track_frame=track_frame)


def test_uncalibrated_construction_still_works_without_ultralytics():
    detector = TrackLimitDetector(fps=10.0, config=CONFIG_PATH)
    assert detector.calibration is None
    assert detector.tracker is not None


def test_car_state_from_reference_point_has_real_per_wheel_data():
    detector = make_detector()
    # pixel (500, 0) -> world (50, 0), the segment's own midpoint. s is
    # measured from build_straight_segment_track's fabricated (extended)
    # loop start, not from p1 -- locate p1's own s first, same as the
    # track/build tests do.
    p1_s, _ = detector.track_frame.to_frenet(0.0, 0.0)
    state = detector.car_state_from_reference_point(u=500.0, v=0.0, frame_id=10)

    assert state.source == "vision"
    assert state.wheel_d is not None
    assert len(state.wheel_d) == 4
    assert state.s == pytest.approx(p1_s + 50.0, abs=0.1)
    assert state.d == pytest.approx(0.0, abs=0.1)
    assert state.reproj_error_px == pytest.approx(detector.calibration.reprojection_error_px)


def test_car_state_wheel_d_reflects_track_width_not_a_single_point():
    detector = make_detector()
    state = detector.car_state_from_reference_point(u=500.0, v=0.0, frame_id=0)
    # half_track_m default is 1.0m either side of the car centre -- the four
    # wheel d-values should NOT all collapse to state.d, unlike a centroid
    assert len(set(round(d, 3) for d in state.wheel_d)) > 1


def test_finalize_produces_a_real_violation_for_a_sustained_offtrack_run():
    detector = make_detector(fps=10.0)
    # 700ms with the car centre at world d=6.0m -- with the default 1m
    # half-track, both wheel pairs (5.0m and 7.0m) clear the 4.1m outer
    # edge, so this is genuinely all four wheels off, not a proxy point.
    for frame_id in range(5, 12):  # 700ms at 10fps
        detector._states.append(detector.car_state_from_reference_point(u=500.0, v=60.0, frame_id=frame_id))

    results = detector.finalize(frame_id=12)
    assert len(results) == 1
    finding, verdict = results[0]
    assert verdict == Verdict.VIOLATION
    assert finding.violation is True


def test_finalize_abstains_correctly_off_the_real_pipeline_too():
    # two wheels off is legal (Art. 33.3): car centre at d=4.5m clears the
    # entry hysteresis threshold, but only the outer wheel pair (5.5m)
    # passes the 4.1m edge -- the inner pair (3.5m) stays on track.
    detector = make_detector(fps=10.0)
    for frame_id in range(5, 12):
        detector._states.append(detector.car_state_from_reference_point(u=500.0, v=45.0, frame_id=frame_id))

    results = detector.finalize(frame_id=12)
    assert len(results) == 1
    finding, verdict = results[0]
    assert verdict != Verdict.VIOLATION


def test_finalize_with_no_states_returns_nothing():
    detector = make_detector()
    assert detector.finalize(frame_id=100) == []
