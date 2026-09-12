"""Data contracts shared across tiers (Apex Assist plan, Section 4).

Every tier boundary is one of these types. Tiers must be independently
testable with synthetic instances of these types — no tier should need a
live instance of another tier to be exercised in a test.
"""
from dataclasses import dataclass
from enum import Enum


@dataclass
class CarState:
    """Tier 0 output. One per car per tick. Sensor-agnostic."""
    car_number: int
    session_time: float          # seconds, single canonical clock
    s: float                     # arc length along centreline, metres
    d: float                     # lateral offset from centreline, metres (+ = left)
    heading: float               # radians
    speed: float                 # m/s
    yaw_rate: float
    wheel_d: tuple[float, float, float, float] | None       # per-wheel lateral offset
    wheel_sigma: tuple[float, float, float, float] | None   # per-wheel 1-sigma, metres
    source: str                  # "vision" | "telemetry" | "fused"
    # evidence quality
    reproj_error_px: float | None
    occlusion_frac: float
    n_sensors: int


@dataclass
class RelationalContext:
    """Who else was around, and where."""
    car_number: int
    session_time: float
    alongside: list[int]         # cars within +/- 1 car length in s
    nearest_delta_s: float
    nearest_delta_d: float
    yellow_flag_sector: bool


class EventType(str, Enum):
    CLEAN = "clean"
    EXCURSION_NO_ADVANTAGE = "excursion_no_advantage"
    EXCURSION_WITH_GAIN = "excursion_with_gain"
    FORCED_OFF = "forced_off"
    AVOIDANCE = "avoidance"
    UNSAFE_REJOIN = "unsafe_rejoin"
    MEASUREMENT_ARTEFACT = "measurement_artefact"


@dataclass
class ExcursionEvent:
    """Tier 1 output. An event has duration and structure."""
    event_id: str
    car_number: int
    lap: int
    corner: int
    t_onset: float
    t_max_excursion: float
    t_reentry: float
    max_margin_m: float          # how far past the boundary at peak
    margin_sigma_m: float
    duration_s: float
    wheels_off_peak: int | None  # 0-4, None if undetermined
    proposed_type: EventType
    relational: RelationalContext


@dataclass
class Finding:
    """Tier 2 output. Deterministic. Always carries its authority."""
    event_id: str
    car_number: int
    lap: int
    corner: int
    session_time: str
    violation: bool
    description: str             # "all four wheels beyond track edge for 620 ms"
    min_margin_cm: float
    margin_uncertainty_cm: float
    authority: list[str]         # ["F1SR Art. 33.3", "Event Notes §22"]
    exceptions_evaluated: dict[str, bool]
    strike_context: str
    corner_monitored: bool


class Verdict(str, Enum):
    NO_VIOLATION = "no_violation"
    VIOLATION = "violation"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass
class TrustVector:
    evidence_quality: float      # [0,1]
    measurement_margin: float    # [0,1]
    model_confidence: float      # [0,1] CALIBRATED
    rule_determinacy: float      # [0,1]
    precedent_consistency: float # [0,1]
    scalar: float                # weighted combination, for queue ranking
    conformal_set: list[Verdict] # size 1 = confident, >1 = ambiguous


@dataclass
class StewardItem:
    """Tier 5 input. What the human sees."""
    finding: Finding
    trust: TrustVector
    verdict: Verdict
    agent_reasoning: str | None    # case for AND against
    evidence_clip_path: str | None
    precedents: list[str]
    priority: float
