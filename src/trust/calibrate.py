"""Calibrated model confidence (Section 5.7): isotonic regression against
labelled outcomes (in a full build, the FIA-document labels from
src/eval/scrape_fia.py), plus expected calibration error (ECE) so the
calibration itself is reported, not just trusted.

Isotonic regression is implemented directly via the pool-adjacent-violators
algorithm rather than pulling in scikit-learn for one function — this
project already avoids training anything (Section 8 anti-goal); fitting an
isotonic map is not training a model, but there's no reason to add a
heavy dependency for ~20 lines of well-known math either.
"""
from __future__ import annotations

import numpy as np


def _pool_adjacent_violators(y_sorted: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Non-decreasing least-squares fit to y_sorted (already ordered by x)."""
    values: list[float] = []
    value_weights: list[float] = []
    counts: list[int] = []

    for y, w in zip(y_sorted, weights):
        v, wt, c = float(y), float(w), 1
        while values and values[-1] > v:
            v = (values[-1] * value_weights[-1] + v * wt) / (value_weights[-1] + wt)
            wt = value_weights[-1] + wt
            c = counts[-1] + c
            values.pop()
            value_weights.pop()
            counts.pop()
        values.append(v)
        value_weights.append(wt)
        counts.append(c)

    fitted = np.empty(len(y_sorted))
    idx = 0
    for v, c in zip(values, counts):
        fitted[idx : idx + c] = v
        idx += c
    return fitted


class IsotonicCalibrator:
    """Maps a raw score to a calibrated probability via a fitted
    monotonic step function; predictions outside the fitted range clip to
    the nearest end.
    """

    def __init__(self) -> None:
        self._x_sorted: np.ndarray | None = None
        self._y_fitted: np.ndarray | None = None

    def fit(self, raw_scores, labels, weights=None) -> "IsotonicCalibrator":
        raw_scores = np.asarray(raw_scores, dtype=float)
        labels = np.asarray(labels, dtype=float)
        if len(raw_scores) == 0:
            raise ValueError("calibration set must be non-empty")
        weights = np.ones(len(raw_scores)) if weights is None else np.asarray(weights, dtype=float)

        order = np.argsort(raw_scores, kind="stable")
        self._x_sorted = raw_scores[order]
        self._y_fitted = _pool_adjacent_violators(labels[order], weights[order])
        return self

    def predict(self, raw_scores):
        if self._x_sorted is None:
            raise RuntimeError("IsotonicCalibrator.fit must be called before predict")
        scalar_input = np.isscalar(raw_scores)
        raw_scores = np.atleast_1d(np.asarray(raw_scores, dtype=float))
        idx = np.searchsorted(self._x_sorted, raw_scores, side="right") - 1
        idx = np.clip(idx, 0, len(self._y_fitted) - 1)
        out = self._y_fitted[idx]
        return float(out[0]) if scalar_input else out


def expected_calibration_error(probs, labels, n_bins: int = 10) -> float:
    """Weighted mean absolute gap between predicted confidence and actual
    outcome frequency, binned by predicted probability. Lower is better;
    a well-calibrated model has ECE near 0.
    """
    probs = np.asarray(probs, dtype=float)
    labels = np.asarray(labels, dtype=float)
    n = len(probs)
    if n == 0:
        raise ValueError("probs/labels must be non-empty")

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (probs >= lo) & (probs <= hi) if i == n_bins - 1 else (probs >= lo) & (probs < hi)
        if not np.any(mask):
            continue
        bin_confidence = probs[mask].mean()
        bin_accuracy = labels[mask].mean()
        ece += (mask.sum() / n) * abs(bin_confidence - bin_accuracy)
    return float(ece)
