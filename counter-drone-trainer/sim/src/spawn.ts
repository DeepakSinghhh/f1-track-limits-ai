import type { Catalogue, DroneClass, Scenario, Tactic, Wave } from "./contracts.ts";
import type { Rng } from "./rng.ts";
import type { Terrain } from "./terrain.ts";
import type { Entity, Role, Waypoint } from "./types.ts";
import { polar, v3, type Vec3 } from "./vec.ts";

export interface SpawnPlan {
  t: number;
  entity: Entity;
  /** recon_then_strike strikers: aim depends on whether the recon survived. */
  dependsOnRecon: string | null;
}

const MAX_ACCEL: Record<DroneClass, number> = {
  bird: 3,
  friendly_uav: 4,
  civil_drone: 4,
  recon_quad: 6,
  fpv_rf: 14,
  fpv_fiber: 14,
  loitering_munition: 7,
  decoy: 7,
};

export const TERMINAL_M: Partial<Record<DroneClass, number>> = {
  fpv_rf: 350,
  fpv_fiber: 350,
  loitering_munition: 900,
  decoy: 900,
};

export function makeEntity(
  cat: Catalogue,
  cls: DroneClass,
  role: Role,
  pos: Vec3,
  t: number,
  rng: Rng,
): Entity {
  const spec = cat.drones[cls];
  return {
    id: "",
    idx: -1,
    cls,
    spec,
    pos,
    vel: v3(),
    flying: true,
    outcome: "active",
    outcomeT: null,
    outcomeBy: null,
    role,
    phase: role === "recon" || role === "strike" ? "ingress" : "loiter",
    waveId: null,
    tactic: null,
    groupId: null,
    route: [],
    wp: 0,
    targetAsset: null,
    aim: null,
    arrivalT: null,
    speed: spec.cruise_mps * rng.range(0.92, 1.08),
    agl: rng.range(spec.alt_m[0], spec.alt_m[1]),
    maxAccel: MAX_ACCEL[cls],
    linkLost: false,
    diverted: false,
    iff: spec.iff,
    tSpawn: t,
    tFirstDisplayed: null,
    trackId: null,
    orbitCenter: null,
    observeT: 0,
    hoverUntil: -1,
    nextHoverT: 0,
    reconDone: false,
    flockId: -1,
    patrolPts: [],
    patrolDir: 1,
    flap: rng.next() * Math.PI * 2,
    holdUntil: -1,
  };
}

function roleFor(cls: DroneClass): Role {
  if (cls === "recon_quad") return "recon";
  if (cls === "bird") return "bird";
  if (cls === "friendly_uav") return "patrol";
  if (cls === "civil_drone") return "wander";
  return "strike";
}

/** Expand every wave and clutter item into concrete, timed spawns. */
export function planSpawns(sc: Scenario, cat: Catalogue, terrain: Terrain, rng: Rng, birdRng: Rng): SpawnPlan[] {
  const plans: SpawnPlan[] = [];
  const assets = new Map(sc.map.assets.map((a) => [a.id, a]));

  for (const wave of sc.waves) {
    const asset = assets.get(wave.target) ?? sc.map.assets[0];
    const target = v3(asset.pos[0], asset.pos[1], 0);
    plans.push(...expandWave(wave, target, asset.id, cat, terrain, rng));
  }

  // Friendly patrols along their corridors.
  for (const ff of sc.clutter.friendly_flights) {
    const cor = sc.map.corridors.find((c) => c.id === ff.corridor);
    if (!cor || cor.points.length < 2) continue;
    const pts = cor.points.map((p) => v3(p[0], p[1], terrain.height(p[0], p[1]) + cor.alt_m));
    const e = makeEntity(cat, "friendly_uav", "patrol", { ...pts[0] }, ff.t, rng);
    e.patrolPts = pts;
    e.wp = 1;
    e.agl = cor.alt_m;
    e.iff = ff.iff;
    e.groupId = ff.id;
    plans.push({ t: ff.t, entity: e, dependsOnRecon: null });
  }

  // Civil drones wander near the first no-fire zone (the town).
  const town = sc.map.no_fire_zones[0];
  for (let i = 0; i < sc.clutter.civil_drones; i++) {
    const home = town ? v3(town.center[0], town.center[1], 0) : polar(v3(), rng.range(0, 360), rng.range(2500, 4000));
    const p = polar(home, rng.range(0, 360), rng.range(0, 400));
    p.z = terrain.height(p.x, p.y) + 50;
    const e = makeEntity(cat, "civil_drone", "wander", p, rng.range(0, 60), rng);
    e.orbitCenter = home;
    e.groupId = `civil-${i}`;
    plans.push({ t: e.tSpawn, entity: e, dependsOnRecon: null });
  }

  // Bird flocks (own stream: adding birds never perturbs anything else).
  for (let f = 0; f < sc.clutter.bird_flocks; f++) {
    const center = polar(v3(), birdRng.range(0, 360), birdRng.range(900, 5500));
    const alt = birdRng.range(25, 150);
    const n = birdRng.int(sc.clutter.birds_per_flock[0], sc.clutter.birds_per_flock[1]);
    for (let k = 0; k < n; k++) {
      const p = v3(center.x + birdRng.gauss() * 25, center.y + birdRng.gauss() * 25, 0);
      p.z = terrain.height(p.x, p.y) + alt + birdRng.gauss() * 5;
      const e = makeEntity(cat, "bird", "bird", p, 0, birdRng);
      e.flockId = f;
      e.agl = alt;
      e.groupId = `flock-${f}`;
      e.orbitCenter = center;
      e.speed = birdRng.range(8, 13);
      plans.push({ t: 0, entity: e, dependsOnRecon: null });
    }
  }

  plans.sort((a, b) => a.t - b.t);
  plans.forEach((p, i) => {
    p.entity.idx = i;
    p.entity.id = `E${String(i + 1).padStart(3, "0")}`;
  });
  return plans;
}

function expandWave(
  wave: Wave,
  target: Vec3,
  assetId: string,
  cat: Catalogue,
  terrain: Terrain,
  rng: Rng,
): SpawnPlan[] {
  const out: SpawnPlan[] = [];
  const units: DroneClass[] = [];
  for (const u of wave.units) for (let i = 0; i < u.n; i++) units.push(u.cls);
  const strikers = units.filter((c) => roleFor(c) === "strike");
  const nGroups = wave.tactic === "split_flank" ? Math.min(3, Math.max(2, Math.ceil(strikers.length / 3))) : 1;
  const flankOffsets = nGroups === 3 ? [-55, 0, 55] : nGroups === 2 ? [-45, 45] : [0];
  let strikeIdx = 0;

  for (const cls of units) {
    const role = roleFor(cls);
    const tactic: Tactic = wave.tactic;
    let t = wave.t + rng.range(0, 6);
    if (tactic === "decoy_first" && cls !== "decoy" && role === "strike") t = wave.t + rng.range(28, 40);
    if (tactic === "recon_then_strike" && role === "strike") t = wave.t + rng.range(65, 80);

    const brg = wave.bearing_deg + rng.range(-wave.spread_deg / 2, wave.spread_deg / 2);
    const spawn = polar(target, brg, wave.range_m + rng.range(-300, 300));
    const e = makeEntity(cat, cls, role, spawn, t, rng);
    e.waveId = wave.id;
    e.tactic = tactic;
    e.targetAsset = assetId;
    if (tactic === "terrain_masked" && role === "strike") e.agl = rng.range(20, 40);
    spawn.z = terrain.height(spawn.x, spawn.y) + e.agl;

    if (role === "recon") {
      const standoff = rng.range(1700, 2400);
      const c = polar(target, brg + rng.range(-15, 15), standoff);
      e.orbitCenter = v3(c.x, c.y, 0);
      e.route = [wp(c, e.agl)];
      e.groupId = `${wave.id}-recon`;
      out.push({ t, entity: e, dependsOnRecon: null });
      continue;
    }

    const g = role === "strike" ? strikeIdx++ % nGroups : 0;
    e.groupId = `${wave.id}-g${g}`;
    const route: Waypoint[] = [];
    if (tactic === "split_flank") {
      const mid = polar(target, wave.bearing_deg + flankOffsets[g] + rng.range(-8, 8), rng.range(3000, 3800));
      route.push(wp(mid, e.agl));
    }
    const aimJitter = 8;
    e.aim = v3(target.x + rng.gauss() * aimJitter, target.y + rng.gauss() * aimJitter, 0);
    route.push(wp(e.aim, e.agl));
    e.route = route;

    if (tactic === "time_on_target" && role === "strike") {
      const arrival = wave.arrival_s ?? (wave.range_m + 1200) / 40 + 25;
      e.arrivalT = wave.t + arrival;
    }
    out.push({
      t,
      entity: e,
      dependsOnRecon: tactic === "recon_then_strike" ? `${wave.id}-recon` : null,
    });
  }
  return out;
}

function wp(p: Vec3, agl: number): Waypoint {
  return { x: p.x, y: p.y, agl };
}
