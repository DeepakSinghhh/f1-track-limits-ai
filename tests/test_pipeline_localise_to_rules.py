"""End-to-end check that Tier 1 (events/localise.py) output feeds
directly into Tier 2 (rules/engine.py) without any adapter — the whole
point of fixing data contracts (Section 4) before writing any tier.
"""
import numpy as np

from src.config import load_event_config
from src.events.localise import localise_events
from src.rules.engine import RuleEngine
from src.schemas import Verdict
from src.track.boundary import Boundary
from tests.test_events_localise import make_flat_boundary, make_stream

CONFIG_PATH = "config/events/red_bull_ring_2023.yaml"


def test_localised_four_wheel_excursion_is_a_violation_end_to_end():
    boundary = make_flat_boundary(half_width=4.0)
    d_profile = [3.0] * 5 + [4.5] * 7 + [3.0] * 8
    states = make_stream(d_profile, wheel_spread=0.3)  # all four wheels clear the edge

    events = localise_events(states, boundary, corner_of=lambda s: 1, lap_of=lambda t: 12)
    assert len(events) == 1

    engine = RuleEngine(load_event_config(CONFIG_PATH))
    finding, verdict = engine.evaluate(events[0])

    assert verdict == Verdict.VIOLATION
    assert finding.violation is True
    assert finding.lap == 12
    assert finding.corner == 1


def test_localised_two_wheel_excursion_is_no_violation_end_to_end():
    boundary = make_flat_boundary(half_width=4.0)
    d_profile = [3.0] * 5 + [4.05] * 7 + [3.0] * 8
    states = make_stream(d_profile, wheel_spread=0.5)  # only the outer pair clears the edge

    events = localise_events(states, boundary, corner_of=lambda s: 1, lap_of=lambda t: 12)
    assert len(events) == 1
    assert events[0].wheels_off_peak == 2

    engine = RuleEngine(load_event_config(CONFIG_PATH))
    finding, verdict = engine.evaluate(events[0])

    assert verdict == Verdict.NO_VIOLATION
    assert finding.violation is False


def test_localised_short_blip_is_an_artefact_end_to_end():
    boundary = make_flat_boundary(half_width=4.0)
    d_profile = [3.0] * 5 + [4.5] + [3.0] * 8
    states = make_stream(d_profile, wheel_spread=0.3)

    events = localise_events(states, boundary, corner_of=lambda s: 1, lap_of=lambda t: 12)
    engine = RuleEngine(load_event_config(CONFIG_PATH))
    finding, verdict = engine.evaluate(events[0])

    assert verdict == Verdict.NO_VIOLATION
    assert "artefact" in finding.description
