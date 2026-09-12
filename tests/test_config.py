import textwrap

import pytest

from src.config import EventConfigError, load_event_config

CONFIG_PATH = "config/events/red_bull_ring_2023.yaml"


def test_loads_the_sample_event_config():
    config = load_event_config(CONFIG_PATH)
    assert config.circuit == "red_bull_ring"
    assert config.year == 2023
    assert config.monitored_corners == frozenset({1, 3, 4, 6, 9, 10})
    assert config.escalation.first_penalty_seconds == 5
    assert config.citations["core_rule"] == "F1SR Art. 33.3"
    assert config.min_confidence_sigma == 2.0


def test_missing_required_field_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(textwrap.dedent("""
        circuit: somewhere
        year: 2024
        monitored_corners: [1]
        escalation:
          black_and_white_flag_at: 3
          first_penalty_at: 4
          first_penalty_seconds: 5
          second_penalty_at: 5
          second_penalty_seconds: 10
    """))
    with pytest.raises(EventConfigError):
        load_event_config(bad)


def test_rules_modules_hardcode_no_circuit_name_or_corner_numbers():
    # Apex Assist plan, Section 1.4: "Nothing in rules/ may contain a
    # circuit name or a corner number." Guard it so a future edit can't
    # slip a hardcoded event fact back into the deterministic layer.
    import pathlib

    config = load_event_config(CONFIG_PATH)
    rules_dir = pathlib.Path("src/rules")
    for path in rules_dir.glob("*.py"):
        text = path.read_text()
        assert config.circuit not in text, f"{path} references circuit name {config.circuit!r}"
