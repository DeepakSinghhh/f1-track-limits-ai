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
