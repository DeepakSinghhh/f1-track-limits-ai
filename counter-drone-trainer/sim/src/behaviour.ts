/**
 * Enemy and clutter behaviour (PLAN.md 6.5): steering with boids-style
 * separation/cohesion inside a group, plus per-role state machines.
 *
 * Tactics are mostly encoded in the routes built by spawn.ts (flank
 * waypoints, decoy timing, time-on-target arrival times); this module flies
 * them, adapts speed for synchronised arrival, dives in the terminal phase,
 * and runs each class's failsafe when it is jammed or spoofed.
 */
import { TERMINAL_M } from "./spawn.ts";
import type { Rng } from "./rng.ts";
import type { Terrain } from "./terrain.ts";
import type { Entity } from "./types.ts";
import { add, clamp, clampLen, dist, dist2, len2, norm, polar, scale, sub, v3, type Vec3 } from "./vec.ts";

export interface BehaviourWorld {
  t: number;
  dt: number;
  terrain: Terrain;
  rng: Rng;
  birdRng: Rng;
  group(id: string | null): Entity[];
  flockCenter(flock: number): Vec3;
  impact(e: Entity): void;
  reconComplete(e: Entity): void;
  exit(e: Entity): void;
  landed(e: Entity): void;
}

const EXIT_RANGE = 9800;

export function updateEntity(e: Entity, w: BehaviourWorld): void {
  if (!e.flying) return;
  e.flap += w.dt * (e.cls === "bird" ? 14 : 0);

  if (e.phase === "falling") {
    e.vel = v3(e.vel.x * 0.985, e.vel.y * 0.985, Math.max(-35, e.vel.z - 9.8 * w.dt));
    integrate(e, w);
    if (e.pos.z <= w.terrain.height(e.pos.x, e.pos.y) + 0.5) {
      e.flying = false;
      e.vel = v3();
    }
    return;
  }

  switch (e.role) {
    case "strike":
      strike(e, w);
      break;
    case "recon":
      recon(e, w);
      break;
    case "patrol":
      patrol(e, w);
      break;
    case "wander":
      wander(e, w);
      break;
    case "bird":
      bird(e, w);
      break;
  }

  if (e.flying && e.phase === "egress" && len2(e.pos) > EXIT_RANGE) w.exit(e);
  // ground collision (low flyers clipping a ridge)
  if (e.flying && e.phase !== "terminal" && e.pos.z < w.terrain.height(e.pos.x, e.pos.y) + 1) {
    e.pos.z = w.terrain.height(e.pos.x, e.pos.y) + 1;
    if (e.vel.z < 0) e.vel.z = 0;
  }
}

function integrate(e: Entity, w: BehaviourWorld): void {
  e.pos = add(e.pos, scale(e.vel, w.dt));
}

/** Steer towards a desired velocity with an acceleration limit. */
function steer(e: Entity, desired: Vec3, w: BehaviourWorld): void {
  const dv = clampLen(sub(desired, e.vel), e.maxAccel * w.dt);
  e.vel = add(e.vel, dv);
  integrate(e, w);
}

/** Horizontal seek at `speed` plus altitude hold at `agl` above the ground ahead. */
function seekVel(e: Entity, target: Vec3, speed: number, agl: number, w: BehaviourWorld): Vec3 {
  const d = sub(target, e.pos);
  d.z = 0;
  const h = norm(d);
  const ahead = add(e.pos, scale(h, 120));
  const groundAhead = Math.max(w.terrain.height(e.pos.x, e.pos.y), w.terrain.height(ahead.x, ahead.y));
  const vz = clamp((groundAhead + agl - e.pos.z) * 0.6, -6, 6);
  return v3(h.x * speed, h.y * speed, vz);
}

function separation(e: Entity, w: BehaviourWorld, radius: number, gain: number): Vec3 {
  let push = v3();
  for (const o of w.group(e.groupId)) {
    if (o === e || !o.flying) continue;
    const d = dist(e.pos, o.pos);
    if (d > 0.01 && d < radius) push = add(push, scale(norm(sub(e.pos, o.pos)), ((radius - d) / radius) * gain));
  }
  return push;
}

function cohesion(e: Entity, w: BehaviourWorld, gain: number): Vec3 {
  const g = w.group(e.groupId).filter((o) => o.flying && o !== e && o.phase === e.phase);
  if (g.length === 0) return v3();
  let c = v3();
  for (const o of g) c = add(c, o.pos);
  c = scale(c, 1 / g.length);
  const d = sub(c, e.pos);
  d.z = 0;
  const l = len2(d);
  return l > 60 ? scale(norm(d), gain) : v3();
}

function remainingPath(e: Entity): number {
  let p: Vec3 = e.pos;
  let total = 0;
  for (let i = e.wp; i < e.route.length; i++) {
    const q = v3(e.route[i].x, e.route[i].y, p.z);
    total += dist2(p, q);
    p = q;
  }
  return total;
}

function strike(e: Entity, w: BehaviourWorld): void {
  const aim = e.aim!;
  const ground = w.terrain.height(aim.x, aim.y) + 2;
  const aimG = v3(aim.x, aim.y, ground);
  const terminalM = TERMINAL_M[e.cls] ?? 400;

  if (e.phase === "terminal") {
    const v = scale(norm(sub(aimG, e.pos)), Math.max(e.spec.terminal_mps, e.spec.cruise_mps));
    steer(e, v, w);
    if (dist(e.pos, aimG) < 25 || e.pos.z <= w.terrain.height(e.pos.x, e.pos.y) + 0.5) w.impact(e);
    return;
  }

  // follow route
  while (e.wp < e.route.length - 1 && dist2(e.pos, v3(e.route[e.wp].x, e.route[e.wp].y, 0)) < 180) e.wp += 1;
  const wpt = e.route[e.wp];
  let speed = e.speed;
  if (e.arrivalT !== null) {
    const left = e.arrivalT - w.t;
    const path = remainingPath(e);
    speed = left > 1 ? clamp(path / left, 0.65 * e.spec.cruise_mps, 1.3 * e.spec.cruise_mps) : 1.3 * e.spec.cruise_mps;
  }
  let v = seekVel(e, v3(wpt.x, wpt.y, 0), speed, wpt.agl, w);
  v = add(v, separation(e, w, 35, 6));
  v = add(v, cohesion(e, w, 1.5));
  steer(e, v, w);
  if (e.wp === e.route.length - 1 && dist2(e.pos, aimG) < terminalM) e.phase = "terminal";
}

function recon(e: Entity, w: BehaviourWorld): void {
  const c = e.orbitCenter!;
  if (e.phase === "hover") {
    // link lost: hover briefly, then fly home
    steer(e, v3(0, 0, 0), w);
    if (w.t >= e.holdUntil) e.phase = "egress";
    return;
  }
  if (e.phase === "egress") {
    const out = polar(v3(), bearingOf(e.pos), EXIT_RANGE + 500);
    steer(e, seekVel(e, out, e.spec.cruise_mps, e.agl, w), w);
    return;
  }
  if (e.phase === "ingress") {
    steer(e, seekVel(e, c, e.speed, e.agl, w), w);
    if (dist2(e.pos, c) < 260) {
      e.phase = "orbit";
      e.nextHoverT = w.t + w.rng.range(6, 14);
    }
    return;
  }
  // orbit with periodic hovers: hovering drops radial speed under the radar's MTI floor
  e.observeT += w.dt;
  if (w.t >= e.nextHoverT && e.hoverUntil < w.t) {
    e.hoverUntil = w.t + w.rng.range(8, 12);
    e.nextHoverT = e.hoverUntil + w.rng.range(15, 25);
  }
  if (w.t < e.hoverUntil) {
    steer(e, v3(0, 0, 0), w);
  } else {
    const rel = sub(e.pos, c);
    rel.z = 0;
    const r = Math.max(1, len2(rel));
    const tangent = v3(-rel.y / r, rel.x / r, 0);
    const radial = scale(norm(rel), clamp((250 - r) * 0.05, -3, 3));
    const ground = w.terrain.height(e.pos.x, e.pos.y);
    const v = add(scale(tangent, 7), radial);
    v.z = clamp((ground + e.agl - e.pos.z) * 0.5, -3, 3);
    steer(e, v, w);
  }
  if (!e.reconDone && e.observeT >= 75) {
    e.reconDone = true;
    w.reconComplete(e);
    e.phase = "egress";
  }
}

function patrol(e: Entity, w: BehaviourWorld): void {
  if (e.phase === "egress") {
    const out = polar(v3(), bearingOf(e.pos), EXIT_RANGE + 500);
    steer(e, seekVel(e, out, e.spec.cruise_mps, e.agl, w), w);
    return;
  }
  const pts = e.patrolPts;
  const target = pts[e.wp];
  if (dist2(e.pos, target) < 200) {
    if (e.wp + e.patrolDir >= pts.length || e.wp + e.patrolDir < 0) e.patrolDir *= -1;
    e.wp += e.patrolDir;
  }
  steer(e, seekVel(e, target, e.speed, e.agl, w), w);
}

function wander(e: Entity, w: BehaviourWorld): void {
  if (e.phase === "falling") return;
  if (e.linkLost) {
    // lands in place
    const ground = w.terrain.height(e.pos.x, e.pos.y);
    steer(e, v3(0, 0, -2), w);
    if (e.pos.z <= ground + 0.5) w.landed(e);
    return;
  }
  if (e.phase === "egress") {
    const out = polar(v3(), bearingOf(e.pos), EXIT_RANGE + 500);
    steer(e, seekVel(e, out, 8, 60, w), w);
    return;
  }
  if (!e.route.length || dist2(e.pos, v3(e.route[0].x, e.route[0].y, 0)) < 40) {
    const home = e.orbitCenter!;
    const p = polar(home, w.rng.range(0, 360), w.rng.range(50, 600));
    e.route = [{ x: p.x, y: p.y, agl: w.rng.range(35, 85) }];
  }
  const r = e.route[0];
  steer(e, seekVel(e, v3(r.x, r.y, 0), e.speed, r.agl, w), w);
}

function bird(e: Entity, w: BehaviourWorld): void {
  const c = w.flockCenter(e.flockId);
  let v = seekVel(e, c, e.speed, e.agl + Math.sin(w.t * 0.3 + e.idx) * 8, w);
  v = add(v, separation(e, w, 8, 4));
  // gusty, erratic flight: occasional jinks make radial speed swing through the MTI floor
  v = add(v, v3(w.birdRng.gauss() * 2.5, w.birdRng.gauss() * 2.5, w.birdRng.gauss() * 0.8));
  steer(e, v, w);
}

export function bearingOf(p: Vec3): number {
  return (Math.atan2(p.x, p.y) * 180) / Math.PI;
}

/** Failsafe when the RF link is jammed (PLAN.md 6.7). */
export function onLinkLost(e: Entity, w: BehaviourWorld): void {
  e.linkLost = true;
  switch (e.cls) {
    case "fpv_rf":
      e.phase = "falling";
      break;
    case "recon_quad":
      e.phase = "hover";
      e.holdUntil = w.t + 3;
      break;
    case "friendly_uav":
      e.phase = "egress";
      break;
    case "civil_drone":
      break; // lands, see wander()
    default:
      break;
  }
}

/** GNSS spoofed: the drone flies confidently to the wrong place. */
export function onDiverted(e: Entity, w: BehaviourWorld): void {
  e.diverted = true;
  if (e.role === "strike" && e.aim) {
    const off = polar(e.aim, w.rng.range(0, 360), w.rng.range(1500, 2600));
    e.aim = v3(off.x, off.y, 0);
    e.route = [{ x: off.x, y: off.y, agl: e.agl }];
    e.wp = 0;
    e.arrivalT = null;
    if (e.phase === "terminal") e.phase = "ingress";
  } else if (e.role === "recon" || e.role === "wander") {
    e.phase = "egress";
  }
}
