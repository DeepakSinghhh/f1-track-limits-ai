"""Data contracts shared by the TypeScript sim and the Python server (PLAN.md 4.2).

These pydantic models are the single source of truth. `scripts/gen_contracts.py`
exports them to `schemas/contracts.schema.json` and generates
`sim/src/contracts.ts` from that schema, so the browser sim, the Node bots and
the server all agree on the same shapes. A test fails if the generated files
are stale.

Coordinates: metres in a local east-north-up frame centred on the main
defended asset. Bearings: degrees clockwise from north.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Vec2 = tuple[float, float]


class Strict(BaseModel):
    # Serialized payloads always carry every field, so the generated TS types
    # mark defaulted fields required (the TS side never sees a missing default).
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

class DroneClass(StrEnum):
    bird = "bird"
    friendly_uav = "friendly_uav"
    civil_drone = "civil_drone"
    recon_quad = "recon_quad"
    fpv_rf = "fpv_rf"
    fpv_fiber = "fpv_fiber"
    loitering_munition = "loitering_munition"
    decoy = "decoy"


class Label(StrEnum):
    """What the trainee can call a track (Classify step)."""
    bird = "bird"
    friendly = "friendly"
    civil = "civil"
    recon = "recon"
    fpv = "fpv"
    loitering = "loitering"
    decoy = "decoy"
    unknown = "unknown"


class ControlLink(StrEnum):
    rf = "rf"
    fiber = "fiber"
    none = "none"


class Nav(StrEnum):
    gnss = "gnss"
    gnss_ins = "gnss_ins"
    manual = "manual"
    none = "none"


class EffectKind(StrEnum):
    rf_jam = "rf_jam"
    gnss_spoof = "gnss_spoof"
    laser = "laser"
    rocket = "rocket"
    missile = "missile"
    sam = "sam"
    gun = "gun"


class SensorType(StrEnum):
    radar = "radar"
    rf = "rf"
    acoustic = "acoustic"
    eoir = "eoir"
    iff = "iff"


class TimeOfDay(StrEnum):
    day = "day"
    dusk = "dusk"
    night = "night"


class Weather(StrEnum):
    clear = "clear"
    haze = "haze"
    rain = "rain"
    fog = "fog"


class RoeState(StrEnum):
    weapons_free = "weapons_free"
    weapons_tight = "weapons_tight"
    weapons_hold = "weapons_hold"


class Tactic(StrEnum):
    direct = "direct"
    split_flank = "split_flank"
    decoy_first = "decoy_first"
    time_on_target = "time_on_target"
    terrain_masked = "terrain_masked"
    recon_then_strike = "recon_then_strike"


class Skill(StrEnum):
    S1 = "S1"  # detection in clutter
    S2 = "S2"  # classification, day
    S3 = "S3"  # classification, night / weather / IR
    S4 = "S4"  # RF-silent threats
    S5 = "S5"  # swarm saturation
    S6 = "S6"  # friendly/civil discrimination, ROE discipline
    S7 = "S7"  # cost-exchange discipline
    S8 = "S8"  # degraded-sensor operations


class Outcome(StrEnum):
    active = "active"          # still flying when the mission ended
    neutralised = "neutralised"  # hard kill
    link_lost = "link_lost"    # RF jammed -> failsafe (crash / land / return home)
    diverted = "diverted"      # GNSS spoofed off course
    leaked = "leaked"          # reached its target
    exited = "exited"          # left the area (recon done, patrol over)
    expended = "expended"      # decoy reached the target area (harmless)


# --------------------------------------------------------------------------
# Catalogue (content/catalogue/*.yaml)
# --------------------------------------------------------------------------

class DroneSpec(Strict):
    name: str
    label: Label
    hostile: bool
    size_m: float
    cruise_mps: float
    terminal_mps: float = 0
    alt_m: Vec2
    rcs_m2: float
    thermal: float = Field(ge=0, le=1, description="IR brightness 0..1")
    acoustic_db: float
    link: ControlLink
    nav: Nav
    rf_band: Optional[str] = None
    iff: bool = False
    cost_inr: int
    damage: float = 0
    source: Optional[str] = None
    illustrative: bool = True


class EffectorSpec(Strict):
    name: str
    kind: EffectKind
    kill: Literal["soft", "hard"]
    range_m: float
    cost_inr: int = Field(description="per activation (soft kill) or per round (hard kill)")
    ammo: Optional[int] = None
    rounds_per_shot: int = 1
    sector_half_deg: float = 0
    duration_s: float = 0
    exposure_s: float = 0
    dwell_s: float = 0
    slew_s: float = 1
    speed_mps: float = 0
    blast_m: float = 0
    pk: float = 0
    cycle_s: float = 0
    needs_los: bool = True
    source: Optional[str] = None
    illustrative: bool = True


class SensorSpec(Strict):
    name: str
    type: SensorType
    range_m: float
    update_s: float
    params: dict[str, float] = {}
    source: Optional[str] = None
    illustrative: bool = True


class WeatherEffect(Strict):
    radar: float
    laser_dwell: float
    laser_ok: bool
    ambient_db: float
    eo_vis_km: float
    ir_vis_km: float


class Catalogue(Strict):
    drones: dict[DroneClass, DroneSpec]
    effectors: dict[str, EffectorSpec]
    sensors: dict[str, SensorSpec]
    effect_matrix: dict[EffectKind, dict[DroneClass, float]]
    laser_dwell: dict[DroneClass, float]
    weather: dict[Weather, WeatherEffect]


# --------------------------------------------------------------------------
# Scenario (generator output, sim input)
# --------------------------------------------------------------------------

class Asset(Strict):
    id: str
    name: str
    type: str
    pos: Vec2
    value: float
    radius_m: float = 60


class NoFireZone(Strict):
    id: str
    name: str
    center: Vec2
    radius_m: float


class Corridor(Strict):
    id: str
    name: str
    points: list[Vec2]
    alt_m: float


class MapSpec(Strict):
    terrain_seed: int
    terrain: Literal["plains", "foothills"]
    size_m: float = 16000
    assets: list[Asset]
    no_fire_zones: list[NoFireZone] = []
    corridors: list[Corridor] = []


class Environment(Strict):
    time_of_day: TimeOfDay
    weather: Weather
    ambient_noise_db: float = 45


class Roe(Strict):
    state: RoeState
    authority_delay_s: float = 8


class SensorEvent(Strict):
    t: float
    state: Literal["down", "degraded"]
    for_s: float


class SensorPlacement(Strict):
    id: str
    type: str
    pos: Vec2
    events: list[SensorEvent] = []


class EffectorPlacement(Strict):
    id: str
    type: str
    pos: Vec2
    ammo: Optional[int] = None


class WaveUnit(Strict):
    cls: DroneClass
    n: int


class Wave(Strict):
    id: str
    t: float
    tactic: Tactic
    bearing_deg: float
    spread_deg: float = 20
    range_m: float = 7500
    target: str
    units: list[WaveUnit]
    arrival_s: Optional[float] = None


class FriendlyFlight(Strict):
    id: str
    corridor: str
    t: float
    iff: bool = True


class Clutter(Strict):
    bird_flocks: int = 0
    birds_per_flock: Vec2 = (3, 7)
    friendly_flights: list[FriendlyFlight] = []
    civil_drones: int = 0


class Difficulty(Strict):
    level: float = 0.3
    focus: list[Skill] = []
    load: dict[Skill, float] = {}


class Scenario(Strict):
    id: str
    name: str
    seed: int
    mode: Literal["scripted", "procedural", "benchmark", "drill"]
    briefing: str
    intel: str = ""
    duration_s: float = 420
    map: MapSpec
    environment: Environment
    roe: Roe
    sensors: list[SensorPlacement]
    effectors: list[EffectorPlacement]
    waves: list[Wave]
    clutter: Clutter = Clutter()
    difficulty: Difficulty = Difficulty()
    tags: list[str] = []
    fingerprint: str = ""


# --------------------------------------------------------------------------
# Session result (sim output, server input)
# --------------------------------------------------------------------------

class EventType(StrEnum):
    session_start = "session_start"
    session_end = "session_end"
    track_new = "track_new"
    track_lost = "track_lost"
    track_regained = "track_regained"
    hook = "hook"
    classify = "classify"
    ai_suggestion = "ai_suggestion"
    decision = "decision"
    authority_request = "authority_request"
    authority_granted = "authority_granted"
    engage_order = "engage_order"
    engage_blocked = "engage_blocked"
    engage_result = "engage_result"
    cease = "cease"
    neutralised = "neutralised"
    link_lost = "link_lost"
    diverted = "diverted"
    leaker = "leaker"
    exited = "exited"
    expended = "expended"
    recon_complete = "recon_complete"
    collateral = "collateral"
    friendly_affected = "friendly_affected"
    sensor_state = "sensor_state"
    camera = "camera"
    camera_designate = "camera_designate"
    pause = "pause"
    resume = "resume"


class SimEvent(Strict):
    t: float
    type: EventType
    actor: Literal["trainee", "sim", "bot"]
    track: Optional[str] = None
    entity: Optional[str] = None
    data: dict[str, Any] = {}


class TruthEntity(Strict):
    id: str
    cls: DroneClass
    label: Label
    hostile: bool
    link: ControlLink
    nav: Nav
    cost_inr: int
    damage: float
    wave: Optional[str] = None
    tactic: Optional[Tactic] = None
    iff: bool = False
    track: Optional[str] = None
    t_spawn: float
    t_first_displayed: Optional[float] = None
    outcome: Outcome
    outcome_t: Optional[float] = None
    outcome_by: Optional[str] = None


class ReplayEntity(Strict):
    id: str
    cls: DroneClass


class ReplayFrame(Strict):
    t: float
    e: list[float] = Field(description="per entity: index, x, y, z, state(0 active,1 down)")
    tr: list[float] = Field(description="per track: index, x, y, displayed, label idx, decision idx, hooked")
    cam: list[float] = Field(description="az_deg, el_deg, fov_deg, mode(0 eo,1 ir)")
    fx: list[float] = Field(description="per active effector: effector idx, track idx")


class Replay(Strict):
    dt: float
    entities: list[ReplayEntity]
    tracks: list[str]
    effectors: list[str]
    frames: list[ReplayFrame]


class SessionResult(Strict):
    scenario_id: str
    seed: int
    actor: Literal["trainee", "bot"]
    bot: Optional[str] = None
    duration_s: float
    ended_reason: Literal["all_resolved", "time_up", "aborted"]
    assets_health: dict[str, float]
    aid_mode: Literal["off", "honest", "unreliable"] = "off"
    events: list[SimEvent]
    truth: list[TruthEntity]
    replay: Optional[Replay] = None


#: Everything the TypeScript side needs a generated type for.
EXPORTED = [
    Catalogue, Scenario, SessionResult, SimEvent, TruthEntity, Replay,
]
