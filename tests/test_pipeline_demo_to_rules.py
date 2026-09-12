"""End-to-end check that the demo pipeline's candidate events (single
reference point, no per-wheel data) are honestly evaluated by the same
Tier 2 rule engine as the rest of the system — they should always abstain
with INSUFFICIENT_EVIDENCE for the Art. 33.3 wheel-count test, never a
guessed violation.
"""
from src.config import load_event_config
from src.geofence import ZoneCrossingTracker
from src.rules.engine import RuleEngine
from src.schemas import Verdict

CONFIG_PATH = "config/events/demo_clip.yaml"


def test_sustained_candidate_is_insufficient_evidence_not_a_guessed_violation():
    tracker = ZoneCrossingTracker(fps=10, min_duration_s=0.150)
    tracker.update(True, 5)
    event = tracker.update(False, 12)  # 700ms, well past the duration gate

    engine = RuleEngine(load_event_config(CONFIG_PATH))
    finding, verdict = engine.evaluate(event)

    assert verdict == Verdict.INSUFFICIENT_EVIDENCE
    assert finding.violation is False
    assert "unavailable" in finding.description


def test_short_candidate_is_also_insufficient_evidence():
    # left_the_track checks for missing wheel data before the duration
    # gate, so with wheels_off_peak always None in this demo, even a
    # sub-gate blip abstains rather than being waved through as "clean" --
    # the missing measurement is reported either way, not just for the
    # sustained case.
    tracker = ZoneCrossingTracker(fps=10, min_duration_s=0.150)
    tracker.update(True, 5)
    event = tracker.update(False, 6)  # 100ms

    engine = RuleEngine(load_event_config(CONFIG_PATH))
    finding, verdict = engine.evaluate(event)

    assert verdict == Verdict.INSUFFICIENT_EVIDENCE
    assert "unavailable" in finding.description


def test_finding_still_carries_real_citations_and_exceptions():
    tracker = ZoneCrossingTracker(fps=10, min_duration_s=0.150)
    tracker.update(True, 5)
    event = tracker.update(False, 12)

    engine = RuleEngine(load_event_config(CONFIG_PATH))
    finding, _ = engine.evaluate(event)

    assert finding.authority == ["F1SR Art. 33.3", "FIA Driving Standards Guidelines v4.1"]
    assert finding.exceptions_evaluated == {
        "forced_off": False,
        "avoidance": False,
        "already_penalized": False,
        "corner_not_monitored": False,
    }
