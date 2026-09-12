"""Evaluation metrics (Section 5.11) for measuring the system against
real outcomes once src/eval/scrape_fia.py produces labelled ground truth.
Every function here takes plain lists/arrays rather than a scraper's
output type, so it is usable (and testable) without that scraper existing
yet — and reusable for any other source of labelled incidents later.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.schemas import Verdict


@dataclass(frozen=True)
class PrecisionRecall:
    precision: float
    recall: float
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int


def precision_recall(predicted: list[Verdict], actual: list[Verdict]) -> PrecisionRecall:
    """Incident-level precision/recall against ground truth (e.g. FIA
    stewards' decisions). "violation" is the positive class;
    NO_VIOLATION and INSUFFICIENT_EVIDENCE both count as a negative
    prediction — an abstention is not a flag.

    Recall matters most here (Section 5.11: "a missed violation is worse
    than a queued false positive") — report it prominently wherever this
    is surfaced, not buried next to precision as if the two traded off
    symmetrically for this use case.
    """
    if len(predicted) != len(actual):
        raise ValueError("predicted and actual must be the same length")
    if not predicted:
        raise ValueError("predicted/actual must be non-empty")

    tp = fp = fn = tn = 0
    for p, a in zip(predicted, actual):
        p_positive = p == Verdict.VIOLATION
        a_positive = a == Verdict.VIOLATION
        if p_positive and a_positive:
            tp += 1
        elif p_positive and not a_positive:
            fp += 1
        elif not p_positive and a_positive:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    return PrecisionRecall(precision, recall, tp, fp, fn, tn)


def steward_agreement_by_trust_band(
    trust_scalars: list[float],
    system_verdicts: list[Verdict],
    steward_decisions: list[Verdict],
    n_bands: int = 5,
) -> dict[str, float]:
    """Fraction of items where the steward's decision matches the
    system's verdict, binned by trust scalar into n_bands equal-width
    bands over [0, 1]. If calibration is doing its job, disagreement
    should concentrate in the low bands; if it doesn't, that itself is a
    finding to surface, not hide (Section 5.7's whole point).

    Returns a dict keyed by band label ("0.0-0.2", ...) to agreement rate
    (NaN for a band with no items, not 0 — an empty band isn't "always
    disagreed").
    """
    if not (len(trust_scalars) == len(system_verdicts) == len(steward_decisions)):
        raise ValueError("trust_scalars, system_verdicts, steward_decisions must be equal length")
    if not trust_scalars:
        raise ValueError("inputs must be non-empty")

    band_width = 1.0 / n_bands
    matches = [0] * n_bands
    totals = [0] * n_bands

    for scalar, system_verdict, steward_decision in zip(trust_scalars, system_verdicts, steward_decisions):
        band = min(int(scalar / band_width), n_bands - 1)
        totals[band] += 1
        if system_verdict == steward_decision:
            matches[band] += 1

    result = {}
    for b in range(n_bands):
        lo, hi = b * band_width, (b + 1) * band_width
        label = f"{lo:.1f}-{hi:.1f}"
        result[label] = (matches[b] / totals[b]) if totals[b] else float("nan")
    return result


def risk_coverage_curve(
    confidences: list[float], correct: list[bool], n_points: int = 20
) -> list[tuple[float, float]]:
    """Standard selective-prediction curve: (coverage, risk) pairs. At
    coverage c, risk is the error rate among the c-fraction most
    confident items (sorted descending by confidence). A confidence
    signal worth trusting keeps risk low at low coverage; as coverage
    approaches 1 every curve converges to the overall error rate.
    """
    n = len(confidences)
    if n == 0 or n != len(correct):
        raise ValueError("confidences and correct must be non-empty and equal length")

    order = sorted(range(n), key=lambda i: -confidences[i])
    correct_sorted = [correct[i] for i in order]

    points = []
    for k in range(1, n_points + 1):
        coverage = k / n_points
        cutoff = max(1, round(coverage * n))
        subset = correct_sorted[:cutoff]
        risk = 1.0 - (sum(subset) / len(subset))
        points.append((coverage, risk))
    return points


def human_review_reduction(total_candidates: int, items_requiring_review: int) -> float:
    """Fraction of candidate excursions the system resolves confidently
    enough that a steward never needs to look at them. 1.0 = nothing
    needs review; 0.0 = everything does. items_requiring_review must not
    exceed total_candidates — review queue items are a subset of
    candidates, never a superset.
    """
    if total_candidates <= 0:
        raise ValueError("total_candidates must be > 0")
    if items_requiring_review < 0 or items_requiring_review > total_candidates:
        raise ValueError("items_requiring_review must be within [0, total_candidates]")
    return 1.0 - (items_requiring_review / total_candidates)


def mean_flag_latency(event_times: list[float], flag_times: list[float]) -> float:
    """Mean seconds between an excursion occurring (its peak or onset,
    caller's choice — pass whichever event_times represents) and the
    system surfacing a Finding for it. Section 8: "No real-time claims
    without a measured latency number" — this is that number.
    """
    if len(event_times) != len(flag_times) or not event_times:
        raise ValueError("event_times and flag_times must be non-empty and equal length")

    latencies = [flag - event for event, flag in zip(event_times, flag_times)]
    return sum(latencies) / len(latencies)
