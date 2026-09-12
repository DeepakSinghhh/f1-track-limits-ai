"""Five independently displayed trust components (Section 5.7).

Each is in [0, 1] and shown to the steward as its own bar, not collapsed
into an opaque single number (Section 8 anti-goal). None of this decides
the regulatory question — rule_determinacy in particular reads facts the
rule engine (Tier 2) already computed (exceptions, relational context)
rather than re-deriving them.
"""
from __future__ import annotations

import numpy as np

from src.schemas import ExcursionEvent, Finding, TrustVector, Verdict

DEFAULT_WEIGHTS = {
    "evidence_quality": 0.20,
    "measurement_margin": 0.25,
    "model_confidence": 0.25,
    "rule_determinacy": 0.15,
    "precedent_consistency": 0.15,
}


def evidence_quality(
    reproj_error_px: float | None,
    occlusion_frac: float,
    n_sensors: int,
    motion_blur: float = 0.0,
) -> float:
    """f(reprojection error, occlusion fraction, motion blur, n_sensors).

    Two agreeing sensors scores far above either alone.
    """
    if reproj_error_px is None:
        reproj_score = 0.5  # telemetry-only: no reprojection error to judge by
    else:
        reproj_score = max(0.0, 1.0 - reproj_error_px / 10.0)  # 10px+ error -> 0

    occlusion_score = max(0.0, 1.0 - occlusion_frac)
    blur_score = max(0.0, 1.0 - motion_blur)
    sensor_bonus = min(n_sensors, 2) / 2.0  # 1 sensor -> 0.5, 2+ agreeing -> 1.0

    score = 0.4 * reproj_score + 0.2 * occlusion_score + 0.2 * blur_score + 0.2 * sensor_bonus
    return float(np.clip(score, 0.0, 1.0))


def measurement_margin(max_margin_m: float, margin_sigma_m: float) -> float:
    """clip(max_margin_m / (3 * margin_sigma_m), 0, 1).

    2cm over with +-5cm uncertainty scores near zero regardless of what
    the point-estimate geometry (or any model) concluded.
    """
    if margin_sigma_m <= 0:
        return 1.0 if max_margin_m > 0 else 0.0
    return float(np.clip(max_margin_m / (3 * margin_sigma_m), 0.0, 1.0))


def rule_determinacy(event: ExcursionEvent, finding: Finding) -> float:
    """1.0 for pure geometry; reduced when an exception nearly triggered,
    a car was alongside during the approach, or under yellow.
    """
    score = 1.0
    if event.relational.alongside:
        score -= 0.3
    if event.relational.yellow_flag_sector:
        score -= 0.3
    if finding.corner_monitored and event.wheels_off_peak in (3, 4) and finding.min_margin_cm < 2.0:
        # Geometrically borderline: a small measurement error would flip
        # the wheel count either side of the violation threshold.
        score -= 0.2
    return float(np.clip(score, 0.0, 1.0))


def precedent_consistency(candidate_verdict: Verdict, prior_verdicts: list[Verdict]) -> float:
    """Agreement with how comparable events were ruled earlier this
    session. Divergence lowers trust and is shown, not hidden. No
    precedents yet is neutral (1.0), not penalised.
    """
    if not prior_verdicts:
        return 1.0
    agreements = sum(1 for v in prior_verdicts if v == candidate_verdict)
    return float(agreements / len(prior_verdicts))


def combine(components: dict[str, float], weights: dict[str, float] = DEFAULT_WEIGHTS) -> float:
    total_weight = sum(weights.values())
    return float(sum(components[name] * weight for name, weight in weights.items()) / total_weight)


def build_trust_vector(
    *,
    evidence_quality_score: float,
    measurement_margin_score: float,
    model_confidence_score: float,
    rule_determinacy_score: float,
    precedent_consistency_score: float,
    conformal_set: list[Verdict],
    weights: dict[str, float] = DEFAULT_WEIGHTS,
) -> TrustVector:
    components = {
        "evidence_quality": evidence_quality_score,
        "measurement_margin": measurement_margin_score,
        "model_confidence": model_confidence_score,
        "rule_determinacy": rule_determinacy_score,
        "precedent_consistency": precedent_consistency_score,
    }
    return TrustVector(
        evidence_quality=evidence_quality_score,
        measurement_margin=measurement_margin_score,
        model_confidence=model_confidence_score,
        rule_determinacy=rule_determinacy_score,
        precedent_consistency=precedent_consistency_score,
        scalar=combine(components, weights),
        conformal_set=conformal_set,
    )


def decide_verdict(tier2_verdict: Verdict, trust: TrustVector, scalar_threshold: float = 0.5) -> Verdict:
    """Section 5.7 abstention policy: "if scalar < threshold or the
    conformal set has >1 element, verdict is INSUFFICIENT_EVIDENCE and the
    item escalates with the missing evidence named."

    Tier 2's own finding (a deterministic fact from the point-estimate
    measurement) is preserved when trust is adequate; Tier 4 only ever
    downgrades it to an abstention, never invents a violation Tier 2
    didn't find.
    """
    if trust.scalar < scalar_threshold or len(trust.conformal_set) > 1:
        return Verdict.INSUFFICIENT_EVIDENCE
    return tier2_verdict
