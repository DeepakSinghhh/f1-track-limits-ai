"""Split conformal prediction over calibrated P(violation) (Section 5.7).

A distribution-free coverage guarantee in ~40 lines: at the requested
alpha, the true label falls in the returned prediction set with
probability >= 1 - alpha, no distributional assumptions needed beyond
exchangeability of the calibration and test items. A singleton set is a
confident recommendation; a two-element set is genuine ambiguity, which
the caller reports as INSUFFICIENT_EVIDENCE rather than picking one.
"""
from __future__ import annotations

import math

import numpy as np

from src.schemas import Verdict


def fit_conformal_quantile(cal_scores, cal_labels, alpha: float = 0.05) -> float:
    """cal_scores: calibrated P(violation) for held-out calibration items.
    cal_labels: 1.0 if the item was actually a violation, else 0.0.
    Returns q_hat, the split-conformal nonconformity quantile for 1 - alpha
    coverage.
    """
    cal_scores = np.asarray(cal_scores, dtype=float)
    cal_labels = np.asarray(cal_labels, dtype=float)
    n = len(cal_scores)
    if n == 0:
        raise ValueError("calibration set must be non-empty")

    # Nonconformity of the item's *true* label: how far the calibrated
    # probability was from certainty in the correct direction.
    nonconformity = np.where(cal_labels == 1, 1 - cal_scores, cal_scores)

    level = min(math.ceil((n + 1) * (1 - alpha)) / n, 1.0)
    return float(np.quantile(nonconformity, level, method="higher"))


def predict_set(p_violation: float, q_hat: float) -> list[Verdict]:
    """Which verdicts are consistent with q_hat at the fitted coverage."""
    prediction_set = []
    if (1 - p_violation) <= q_hat:
        prediction_set.append(Verdict.VIOLATION)
    if p_violation <= q_hat:
        prediction_set.append(Verdict.NO_VIOLATION)

    if not prediction_set:
        # p_violation is less confident, in either direction, than
        # anything the calibration set saw -- q_hat rejects both labels.
        # That is itself a signal of ambiguity, not a reason to guess one:
        # treat it the same as a two-element set rather than picking a
        # side arbitrarily.
        return [Verdict.VIOLATION, Verdict.NO_VIOLATION]

    return prediction_set
