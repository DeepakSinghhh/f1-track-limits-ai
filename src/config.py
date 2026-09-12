"""Loader for per-event configuration (Apex Assist plan, Section 1.4).

Monitored corners, escalation thresholds, and regulation citations are all
weekend-specific Event Notes, not universal constants. They live in
config/events/<circuit>_<year>.yaml and are loaded through this module.
src/rules/ must never import a circuit name or corner number directly —
only an EventConfig instance built here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_REQUIRED_TOP_LEVEL = ("circuit", "year", "monitored_corners", "escalation", "citations")
_REQUIRED_ESCALATION = (
    "black_and_white_flag_at",
    "first_penalty_at",
    "first_penalty_seconds",
    "second_penalty_at",
    "second_penalty_seconds",
)
_REQUIRED_CITATIONS = ("core_rule",)

#: Section 5.4: events shorter than this are rejected as measurement
#: artefacts (kerb strikes, single-frame noise), not evaluated as
#: track-limits events. A detection-methodology parameter, not a
#: regulation, so it lives here rather than in src/rules/ — but it is not
#: circuit-specific either, hence the module-level default.
DEFAULT_MIN_EVENT_DURATION_S = 0.150


@dataclass(frozen=True)
class EscalationConfig:
    black_and_white_flag_at: int
    first_penalty_at: int
    first_penalty_seconds: int
    second_penalty_at: int
    second_penalty_seconds: int


@dataclass(frozen=True)
class EventConfig:
    circuit: str
    year: int
    monitored_corners: frozenset[int]
    white_line_width_m: float
    min_event_duration_s: float
    escalation: EscalationConfig
    citations: dict[str, str]
    source_path: str


class EventConfigError(ValueError):
    """Raised when an event config file is missing required fields."""


def load_event_config(path: str | Path) -> EventConfig:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise EventConfigError(f"{path}: top-level document must be a mapping")

    missing = [key for key in _REQUIRED_TOP_LEVEL if key not in raw]
    if missing:
        raise EventConfigError(f"{path}: missing required field(s): {', '.join(missing)}")

    escalation_raw = raw["escalation"]
    missing_esc = [key for key in _REQUIRED_ESCALATION if key not in escalation_raw]
    if missing_esc:
        raise EventConfigError(f"{path}: escalation missing field(s): {', '.join(missing_esc)}")

    citations_raw = raw["citations"]
    missing_cit = [key for key in _REQUIRED_CITATIONS if key not in citations_raw]
    if missing_cit:
        raise EventConfigError(f"{path}: citations missing field(s): {', '.join(missing_cit)}")

    measurement_raw = raw.get("measurement", {}) or {}

    return EventConfig(
        circuit=raw["circuit"],
        year=int(raw["year"]),
        monitored_corners=frozenset(int(c) for c in raw["monitored_corners"]),
        white_line_width_m=float(raw.get("white_line_width_m", 0.10)),
        min_event_duration_s=float(measurement_raw.get("min_event_duration_s", DEFAULT_MIN_EVENT_DURATION_S)),
        escalation=EscalationConfig(**{k: int(escalation_raw[k]) for k in _REQUIRED_ESCALATION}),
        citations={k: str(v) for k, v in citations_raw.items()},
        source_path=str(path),
    )
