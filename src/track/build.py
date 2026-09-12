"""Track model construction from the envelope of car positions (Section 5.1).

"The field collectively paints the track surface." Given a reference
centreline — used only to bootstrap an (s, d) coordinate system, e.g. one
clean lap's telemetry path or a GeoJSON circuit outline — and the envelope
of car positions across a session, take per-s percentiles of the lateral
offset to estimate the painted track edges, then smooth.
"""
from __future__ import annotations

import numpy as np

from src.track.boundary import Boundary
from src.track.frame import TrackFrame

DEFAULT_EDGE_PERCENTILE = 99.5
DEFAULT_BIN_SIZE_M = 5.0
DEFAULT_SMOOTHING_WINDOW = 5


def build_track(
    reference_centreline_xy,
    car_x,
    car_y,
    white_line_width_m: float,
    edge_percentile: float = DEFAULT_EDGE_PERCENTILE,
    bin_size_m: float = DEFAULT_BIN_SIZE_M,
    smoothing_window: int = DEFAULT_SMOOTHING_WINDOW,
) -> tuple[TrackFrame, Boundary]:
    frame = TrackFrame(reference_centreline_xy)

    car_x = np.asarray(car_x, dtype=float)
    car_y = np.asarray(car_y, dtype=float)
    if len(car_x) != len(car_y) or len(car_x) == 0:
        raise ValueError("car_x and car_y must be non-empty and equal length")

    s_vals = np.empty(len(car_x))
    d_vals = np.empty(len(car_x))
    for idx in range(len(car_x)):
        s_vals[idx], d_vals[idx] = frame.to_frenet(car_x[idx], car_y[idx])

    n_bins = max(int(round(frame.total_length / bin_size_m)), 8)
    bin_edges = np.linspace(0.0, frame.total_length, n_bins + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    bin_idx = np.clip(np.digitize(s_vals, bin_edges) - 1, 0, n_bins - 1)

    fallback = float(np.percentile(np.abs(d_vals), edge_percentile))
    w_left = np.full(n_bins, fallback)
    w_right = np.full(n_bins, fallback)

    for b in range(n_bins):
        in_bin = bin_idx == b
        left = d_vals[in_bin & (d_vals >= 0)]
        right = -d_vals[in_bin & (d_vals < 0)]
        if len(left):
            w_left[b] = float(np.percentile(left, edge_percentile))
        if len(right):
            w_right[b] = float(np.percentile(right, edge_percentile))

    w_left = _smooth_circular(w_left, smoothing_window)
    w_right = _smooth_circular(w_right, smoothing_window)

    boundary = Boundary(
        s_samples=bin_centers,
        painted_half_width_left=w_left,
        painted_half_width_right=w_right,
        white_line_width_m=white_line_width_m,
        total_length=frame.total_length,
    )
    return frame, boundary


def _smooth_circular(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return values
    kernel = np.ones(window) / window
    padded = np.concatenate([values[-window:], values, values[:window]])
    smoothed = np.convolve(padded, kernel, mode="same")
    return smoothed[window:-window]


#: How far past the given segment's own two points to extend it before
#: closing the loop. TrackFrame needs a closed loop; a few seconds of one
#: clip's cars never travel anywhere near this far, so the wraparound at
#: s=0/total_length this creates never practically triggers -- see
#: build_straight_segment_track's docstring for the actual constraint.
_DEFAULT_EXTEND_M = 5000.0

#: How far the fabricated "return path" of the closed loop sits from the
#: real p1-p2 line. This must be far larger than any plausible |d| a real
#: query will ever have (track half-widths of a few metres, wide runoff
#: areas of maybe tens of metres) -- TrackFrame picks whichever segment is
#: nearest by plain Euclidean distance, so a return path even a few
#: centimetres away already wins that contest once |d| exceeds half that
#: gap. Caught by test_straight_segment_left_convention_matches_direction_of_travel
#: and test_straight_segment_round_trips_near_the_segment: an earlier
#: version used a 0.05m hairline here, which silently flipped both the
#: sign and the arc-length position for every query more than 2.5cm off
#: the centreline -- i.e. almost every real query.
_SLIVER_WIDTH_M = 500.0


def build_straight_segment_track(
    p1: tuple[float, float],
    p2: tuple[float, float],
    left_half_width_m: float,
    right_half_width_m: float,
    white_line_width_m: float,
    extend_m: float = _DEFAULT_EXTEND_M,
) -> tuple[TrackFrame, Boundary]:
    """A minimal, straight local track model for one short clip's visible
    span, built from just the two points an operator supplies alongside a
    homography -- NOT a substitute for build_track's real per-circuit
    envelope model, which needs a lap's worth of telemetry or a GeoJSON
    outline that a single uploaded clip doesn't have.

    TrackFrame requires a closed loop; this fabricates one by extending
    the p1->p2 line far past the segment in both directions and closing
    it with a hairline offset, forming a long thin "sliver" loop. Valid
    only near the original p1-p2 line, for roughly extend_m metres either
    side of it -- do not reuse the returned TrackFrame for anything
    beyond the clip it was built for, and do not shrink extend_m below
    what the clip's cars could plausibly travel (default 5km comfortably
    covers any single race-footage clip).
    """
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    length = float(np.hypot(dx, dy))
    if length == 0:
        raise ValueError("p1 and p2 must be different points")

    ux, uy = dx / length, dy / length  # unit direction, p1 -> p2
    nx, ny = -uy, ux                   # left-hand normal, matching TrackFrame's own convention

    start = (x1 - ux * extend_m, y1 - uy * extend_m)
    end = (x2 + ux * extend_m, y2 + uy * extend_m)
    centreline = np.array([
        start,
        end,
        (end[0] + nx * _SLIVER_WIDTH_M, end[1] + ny * _SLIVER_WIDTH_M),
        (start[0] + nx * _SLIVER_WIDTH_M, start[1] + ny * _SLIVER_WIDTH_M),
    ])

    frame = TrackFrame(centreline)
    total_length = frame.total_length
    s_samples = np.array([0.0, total_length / 2])  # constant half-width -> two samples suffice
    boundary = Boundary(
        s_samples=s_samples,
        painted_half_width_left=np.full(2, left_half_width_m),
        painted_half_width_right=np.full(2, right_half_width_m),
        white_line_width_m=white_line_width_m,
        total_length=total_length,
    )
    return frame, boundary
