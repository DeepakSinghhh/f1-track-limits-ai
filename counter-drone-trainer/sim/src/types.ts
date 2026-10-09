import type {
  DroneClass,
  DroneSpec,
  EffectKind,
  EffectorSpec,
  Label,
  Outcome,
  RoeState,
  SensorSpec,
  SensorType,
  Tactic,
} from "./contracts.ts";
import type { Vec3 } from "./vec.ts";

export type Role = "strike" | "recon" | "patrol" | "wander" | "bird";
export type Phase = "ingress" | "terminal" | "orbit" | "egress" | "falling" | "loiter" | "hover";

/** A route point: ground position plus height above ground. */
export interface Waypoint {
  x: number;
  y: number;
  agl: number;
}

/** Ground truth. Never shown on the C2 display (only the camera renders it). */
export interface Entity {
  id: string;
  idx: number;
  cls: DroneClass;
  spec: DroneSpec;
  pos: Vec3;
  vel: Vec3;
  flying: boolean;
  outcome: Outcome;
  outcomeT: number | null;
  outcomeBy: string | null;
  role: Role;
  phase: Phase;
  waveId: string | null;
  tactic: Tactic | null;
  groupId: string | null;
  route: Waypoint[];
  wp: number;
  targetAsset: string | null;
  aim: Vec3 | null;
  arrivalT: number | null;
  speed: number;
  agl: number;
  maxAccel: number;
  linkLost: boolean;
  diverted: boolean;
  iff: boolean;
  tSpawn: number;
  tFirstDisplayed: number | null;
  trackId: string | null;
  // behaviour state
  orbitCenter: Vec3 | null;
  observeT: number;
  hoverUntil: number;
  nextHoverT: number;
  reconDone: boolean;
  flockId: number;
  patrolPts: Vec3[];
  patrolDir: number;
  flap: number;
  holdUntil: number;
}

export type Hostility = "unknown" | "hostile" | "friend" | "neutral";
export type Decision = "none" | "ignore" | "monitor" | "engage";

export interface Track {
  id: string;
  idx: number;
  entityId: string;
  est: Vec3;
  vel: Vec3;
  lastFix: number;
  firstFix: number;
  displayed: boolean;
  src: { radar: number; rf: number; ac: number; cam: number };
  rfBand: string | null;
  iff: "pending" | "friend" | "no_reply" | "unavailable";
  hooked: boolean;
  hookT: number | null;
  label: Label;
  labelT: number | null;
  decision: Decision;
  authority: "none" | "requested" | "granted";
  authorityAt: number | null;
  engagedBy: string[];
  down: boolean;
  downT: number | null;
  /** kinematic history for the classification aid: [speed, climb] samples */
  speedSamples: number[];
  altSamples: number[];
  thermalSeen: number | null;
}

export interface SensorState {
  id: string;
  idx: number;
  type: SensorType;
  spec: SensorSpec;
  pos: Vec3;
  status: "ok" | "down" | "degraded";
  nextUpdate: number;
}

export interface EffectorState {
  id: string;
  idx: number;
  type: string;
  spec: EffectorSpec;
  pos: Vec3;
  ammo: number | null;
  status: "ready" | "slewing" | "active" | "empty";
  orderId: number;
  targetTrack: string | null;
  targetEntity: string | null;
  bearing: number;
  until: number;
  readyAt: number;
  nextShotT: number;
  dwell: number;
  outOfRangeSince: number | null;
  affected: Set<string>;
  exposure: Map<string, number>;
  rolled: Set<string>;
  collateralLogged: boolean;
}

export interface Projectile {
  kind: EffectKind;
  effectorId: string;
  orderId: number;
  trackId: string;
  targetEntity: string | null;
  from: Vec3;
  aim: Vec3;
  fireT: number;
  impactT: number;
  pk: number;
  blast: number;
}

export interface Strobe {
  sensor: "rf" | "ac";
  entityId: string;
  from: Vec3;
  bearing: number;
  band: string | null;
  t: number;
}

export interface CameraState {
  az: number;
  el: number;
  fov: number;
  mode: "eo" | "ir";
  targetAz: number;
  targetEl: number;
  cueTrack: string | null;
  lockEntity: string | null;
  lockTrack: string | null;
}

// ---------------------------------------------------------------------------
// View model for the UI (no ground truth in here).
// ---------------------------------------------------------------------------

export interface TrackView {
  id: string;
  x: number;
  y: number;
  z: number;
  agl: number;
  vx: number;
  vy: number;
  vz: number;
  speed: number;
  range: number;
  bearing: number;
  tti: number | null;
  displayed: boolean;
  down: boolean;
  hooked: boolean;
  label: Label;
  hostility: Hostility;
  decision: Decision;
  authority: "none" | "requested" | "granted";
  iff: Track["iff"];
  sources: { radar: boolean; rf: boolean; ac: boolean; cam: boolean };
  rfBand: string | null;
  engagedBy: string[];
  age: number;
  aid: AidSuggestion | null;
}

export interface AidSuggestion {
  label: Label;
  p: number;
  reasons: string[];
  probs: Partial<Record<Label, number>>;
}

export interface StrobeView {
  sensor: "rf" | "ac";
  x0: number;
  y0: number;
  bearing: number;
  band: string | null;
}

export interface EffectorView {
  id: string;
  type: string;
  name: string;
  kind: EffectKind;
  kill: "soft" | "hard";
  x: number;
  y: number;
  range: number;
  status: EffectorState["status"];
  ammo: number | null;
  costPerUse: number;
  targetTrack: string | null;
  sector: { bearing: number; half: number } | null;
  progress: number | null;
}

export interface ShotView {
  kind: EffectKind;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  age: number;
}

export interface SensorView {
  id: string;
  type: SensorType;
  name: string;
  status: SensorState["status"];
  x: number;
  y: number;
  range: number;
}

export interface FeedItem {
  t: number;
  text: string;
  level: "info" | "warn" | "alert" | "good";
}

export interface SimView {
  t: number;
  duration: number;
  tracks: TrackView[];
  strobes: StrobeView[];
  effectors: EffectorView[];
  shots: ShotView[];
  sensors: SensorView[];
  camera: CameraState;
  roe: RoeState;
  assets: { id: string; name: string; health: number }[];
  spend: number;
  ended: boolean;
  endReason: string | null;
  feed: FeedItem[];
}

/** What the EO/IR camera renders (ground truth, but only as pixels). */
export interface Renderable {
  id: string;
  cls: DroneClass;
  x: number;
  y: number;
  z: number;
  heading: number;
  pitch: number;
  flying: boolean;
  flap: number;
  size: number;
  thermal: number;
}

export interface CommandResult {
  ok: boolean;
  reason?: string;
}
