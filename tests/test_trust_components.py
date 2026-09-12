from src.rules.engine import RuleEngine
from src.config import load_event_config
from src.schemas import Verdict
from src.trust.components import (
    build_trust_vector,
    combine,
    decide_verdict,
    evidence_quality,
    measurement_margin,
    precedent_consistency,
    rule_determinacy,
)
from tests.factories import make_event

CONFIG_PATH = "config/events/red_bull_ring_2023.yaml"


def test_evidence_quality_rewards_two_agreeing_sensors():
    one_sensor = evidence_quality(reproj_error_px=1.0, occlusion_frac=0.0, n_sensors=1)
    two_sensors = evidence_quality(reproj_error_px=1.0, occlusion_frac=0.0, n_sensors=2)
    assert two_sensors > one_sensor
    assert 0.0 <= one_sensor <= 1.0
    assert 0.0 <= two_sensors <= 1.0


def test_evidence_quality_penalises_large_reprojection_error():
    good = evidence_quality(reproj_error_px=0.5, occlusion_frac=0.0, n_sensors=2)
    bad = evidence_quality(reproj_error_px=20.0, occlusion_frac=0.0, n_sensors=2)
    assert good > bad


def test_measurement_margin_clips_to_unit_interval():
    assert measurement_margin(max_margin_m=0.30, margin_sigma_m=0.01) == 1.0
    assert measurement_margin(max_margin_m=0.0, margin_sigma_m=0.02) == 0.0
    near_zero = measurement_margin(max_margin_m=0.02, margin_sigma_m=0.02)
    assert 0.0 < near_zero < 1.0


def test_measurement_margin_matches_2cm_over_5cm_uncertainty_is_low_trust():
    score = measurement_margin(max_margin_m=0.02, margin_sigma_m=0.05)
    assert score < 0.2  # "2 cm over with +-5 cm uncertainty scores near zero"


def test_rule_determinacy_reduced_when_alongside_or_yellow():
    engine = RuleEngine(load_event_config(CONFIG_PATH))
    clean_event = make_event(corner=1, wheels_off_peak=4, duration_s=0.62, max_margin_m=0.30)
    finding, _ = engine.evaluate(clean_event)
    clean_score = rule_determinacy(clean_event, finding)
    assert clean_score == 1.0

    from src.schemas import RelationalContext

    alongside_event = make_event(corner=1, wheels_off_peak=4, duration_s=0.62, max_margin_m=0.30)
    alongside_event.relational = RelationalContext(
        car_number=alongside_event.car_number,
        session_time=0.0,
        alongside=[7],
        nearest_delta_s=1.0,
        nearest_delta_d=1.0,
        yellow_flag_sector=False,
    )
    finding2, _ = engine.evaluate(alongside_event)
    assert rule_determinacy(alongside_event, finding2) < clean_score


def test_precedent_consistency_neutral_with_no_history():
    assert precedent_consistency(Verdict.VIOLATION, []) == 1.0


def test_precedent_consistency_measures_agreement():
    history = [Verdict.VIOLATION, Verdict.VIOLATION, Verdict.NO_VIOLATION]
    assert precedent_consistency(Verdict.VIOLATION, history) == 2 / 3


def test_combine_is_a_weighted_average_in_unit_interval():
    scalar = combine(
        {
            "evidence_quality": 1.0,
            "measurement_margin": 1.0,
            "model_confidence": 1.0,
            "rule_determinacy": 1.0,
            "precedent_consistency": 1.0,
        }
    )
    assert scalar == 1.0

    scalar_zero = combine(
        {
            "evidence_quality": 0.0,
            "measurement_margin": 0.0,
            "model_confidence": 0.0,
            "rule_determinacy": 0.0,
            "precedent_consistency": 0.0,
        }
    )
    assert scalar_zero == 0.0


def test_decide_verdict_abstains_below_scalar_threshold():
    trust = build_trust_vector(
        evidence_quality_score=0.2,
        measurement_margin_score=0.2,
        model_confidence_score=0.2,
        rule_determinacy_score=0.2,
        precedent_consistency_score=0.2,
        conformal_set=[Verdict.VIOLATION],
    )
    assert trust.scalar < 0.5
    assert decide_verdict(Verdict.VIOLATION, trust, scalar_threshold=0.5) == Verdict.INSUFFICIENT_EVIDENCE


def test_decide_verdict_abstains_on_ambiguous_conformal_set():
    trust = build_trust_vector(
        evidence_quality_score=0.9,
        measurement_margin_score=0.9,
        model_confidence_score=0.9,
        rule_determinacy_score=0.9,
        precedent_consistency_score=0.9,
        conformal_set=[Verdict.VIOLATION, Verdict.NO_VIOLATION],
    )
    assert decide_verdict(Verdict.VIOLATION, trust, scalar_threshold=0.5) == Verdict.INSUFFICIENT_EVIDENCE


def test_decide_verdict_preserves_tier2_verdict_when_confident():
    trust = build_trust_vector(
        evidence_quality_score=0.9,
        measurement_margin_score=0.9,
        model_confidence_score=0.9,
        rule_determinacy_score=0.9,
        precedent_consistency_score=0.9,
        conformal_set=[Verdict.VIOLATION],
    )
    assert decide_verdict(Verdict.VIOLATION, trust, scalar_threshold=0.5) == Verdict.VIOLATION


def test_decide_verdict_never_invents_a_violation_tier2_did_not_find():
    trust = build_trust_vector(
        evidence_quality_score=0.9,
        measurement_margin_score=0.9,
        model_confidence_score=0.9,
        rule_determinacy_score=0.9,
        precedent_consistency_score=0.9,
        conformal_set=[Verdict.NO_VIOLATION],
    )
    assert decide_verdict(Verdict.NO_VIOLATION, trust, scalar_threshold=0.5) == Verdict.NO_VIOLATION
