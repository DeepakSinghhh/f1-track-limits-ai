/**
 * Engagement resolution (PLAN.md 6.7). The trainee picks a target and an
 * effector; this module checks range / line of sight / ammo / weather,
 * resolves the outcome probabilistically from the effect matrix, and logs
 * every fact the scorer needs (cost, ROE state, friendlies in a jam sector,
 * collateral over no-fire zones). ROE is deliberately NOT enforced here:
 * breaking it is a decision the trainee can make and the scorer grades.
 */
import type { Sim } from "./sim.ts";
import type { CommandResult, EffectorState, Entity, Projectile, Track } from "./types.ts";
import { add, angleDiff, bearing, dist, dist2, scale, v3, type Vec3 } from "./vec.ts";

const LOCK_TOLERANCE_M = 60;
const BREAK_LOCK_S = 3;

export function effectorReady(sim: Sim, f: EffectorState): boolean {
  return f.status === "ready" && sim.t >= f.readyAt;
}

export function engage(sim: Sim, f: EffectorState, tr: Track, actor: "trainee" | "bot"): CommandResult {
  const spec = f.spec;
  const block = (reason: string): CommandResult => {
    sim.emit("engage_blocked", { track: tr.id, actor, data: { effector: f.id, kind: spec.kind, reason } });
    return { ok: false, reason };
  };
  if (tr.down) return block("target already down");
  if (!tr.displayed) return block("no current track");
  if (f.status === "empty" || (f.ammo !== null && f.ammo < spec.rounds_per_shot)) return block("out of ammunition");
  if (!effectorReady(sim, f)) return block(f.status === "ready" ? "reloading" : "effector busy");
  const est = sim.predicted(tr);
  const range = dist(f.pos, est);
  if (range > spec.range_m) return block(`out of range (${(range / 1000).toFixed(1)} km > ${(spec.range_m / 1000).toFixed(1)} km)`);
  if (spec.needs_los && !sim.terrain.los(f.pos, est)) return block("no line of sight");
  if (spec.kind === "laser" && !sim.weatherFx().laser_ok) return block("laser unavailable in fog");

  f.orderId = ++sim.orderSeq;
  f.targetTrack = tr.id;
  f.targetEntity = tr.entityId;
  f.bearing = bearing(f.pos, est);
  f.status = "slewing";
  f.readyAt = sim.t + spec.slew_s;
  f.dwell = 0;
  f.outOfRangeSince = null;
  f.affected = new Set();
  f.exposure = new Map();
  f.rolled = new Set();
  f.collateralLogged = false;
  sim.orderSpent.set(f.orderId, 0);

  const target = sim.byId.get(tr.entityId)!;
  const friendliesInSector =
    spec.kind === "rf_jam" || spec.kind === "gnss_spoof"
      ? sim.entities.filter((e) => e.flying && !e.spec.hostile && e.cls !== "bird" && inSector(f, e)).length
      : 0;
  if (!tr.engagedBy.includes(f.id)) tr.engagedBy.push(f.id);
  tr.decision = "engage";
  if (!tr.hooked) sim.hook(tr.id, actor);
  sim.emit("engage_order", {
    track: tr.id,
    entity: target.id,
    actor,
    data: {
      order: f.orderId,
      effector: f.id,
      type: f.type,
      kind: spec.kind,
      kill: spec.kill,
      unit_cost: spec.cost_inr,
      est_cost: spec.cost_inr * (spec.kill === "soft" ? 1 : spec.rounds_per_shot),
      roe: sim.roe,
      label: tr.label,
      authority: tr.authority,
      n_active: sim.activeTrackCount(),
      tti: sim.tti(tr),
      range: Math.round(range),
      over_nfz: sim.inNoFireZone(est),
      friendlies_in_sector: friendliesInSector,
    },
  });
  sim.say(`${tr.id} ← ${spec.name}`, "info");
  return { ok: true };
}

export function cease(sim: Sim, f: EffectorState, actor: "trainee" | "bot", reason = "ceased"): void {
  if (f.status !== "active" && f.status !== "slewing") return;
  sim.emit("cease", { track: f.targetTrack, actor, data: { effector: f.id, order: f.orderId } });
  finish(sim, f, reason === "ceased" ? "ceased" : reason);
}

function finish(sim: Sim, f: EffectorState, result: string): void {
  const spent = sim.orderSpent.get(f.orderId) ?? 0;
  sim.emit("engage_result", {
    track: f.targetTrack,
    entity: f.targetEntity,
    data: { order: f.orderId, effector: f.id, kind: f.spec.kind, result, spent },
  });
  const label = { kill: "SPLASH", link_lost: "LINK LOST", diverted: "DIVERTED", no_effect: "NO EFFECT", broke_lock: "BROKE LOCK", no_lock: "NO LOCK", miss: "MISS", out_of_ammo: "OUT OF AMMO", ceased: "CEASED", target_gone: "TARGET GONE" }[result] ?? result.toUpperCase();
  const good = result === "kill" || result === "link_lost" || result === "diverted";
  sim.say(`${f.targetTrack} ${f.spec.name}: ${label}`, good ? "good" : result === "ceased" || result === "target_gone" ? "info" : "warn");
  f.status = f.ammo !== null && f.ammo < f.spec.rounds_per_shot ? "empty" : "ready";
  f.readyAt = Math.max(f.readyAt, sim.t + (f.spec.kind === "rocket" ? 3 : 1));
  f.targetTrack = null;
  f.targetEntity = null;
}

function charge(sim: Sim, f: EffectorState, amount: number): void {
  sim.spend += amount;
  sim.orderSpent.set(f.orderId, (sim.orderSpent.get(f.orderId) ?? 0) + amount);
}

export function inSector(f: EffectorState, e: Entity): boolean {
  if (dist(f.pos, e.pos) > f.spec.range_m) return false;
  return Math.abs(angleDiff(bearing(f.pos, e.pos), f.bearing)) <= f.spec.sector_half_deg;
}

/** Per-tick processing for every effector. */
export function runEffectors(sim: Sim): void {
  for (const f of sim.effectors) {
    if (f.status === "slewing" && sim.t >= f.readyAt) activate(sim, f);
    if (f.status !== "active") continue;
    switch (f.spec.kind) {
      case "rf_jam":
      case "gnss_spoof":
        runSector(sim, f);
        break;
      case "laser":
        runLaser(sim, f);
        break;
      case "gun":
        runGun(sim, f);
        break;
      default:
        break;
    }
  }
  runProjectiles(sim);
}

function activate(sim: Sim, f: EffectorState): void {
  const tr = sim.trackById.get(f.targetTrack ?? "");
  const target = f.targetEntity ? sim.byId.get(f.targetEntity) : undefined;
  if (!tr || !target) return finish(sim, f, "target_gone");
  const spec = f.spec;
  f.status = "active";
  switch (spec.kind) {
    case "rf_jam":
    case "gnss_spoof":
      charge(sim, f, spec.cost_inr);
      f.until = sim.t + spec.duration_s;
      break;
    case "laser":
      charge(sim, f, spec.cost_inr);
      if (!target.flying || dist(sim.predicted(tr), target.pos) > LOCK_TOLERANCE_M) return finish(sim, f, "no_lock");
      break;
    case "gun":
      f.nextShotT = sim.t;
      break;
    case "rocket":
    case "missile":
    case "sam":
      launch(sim, f, tr, target);
      break;
  }
}

function runSector(sim: Sim, f: EffectorState): void {
  const spec = f.spec;
  const fx = sim.cat.effect_matrix[spec.kind] ?? {};
  for (const e of sim.entities) {
    if (!e.flying || f.rolled.has(e.id) || !inSector(f, e)) continue;
    const p = fx[e.cls] ?? 0;
    if (p <= 0) continue;
    if (spec.kind === "rf_jam" && (e.spec.link !== "rf" || e.linkLost)) continue;
    if (spec.kind === "gnss_spoof" && (e.diverted || !(e.spec.nav === "gnss" || e.spec.nav === "gnss_ins"))) continue;
    const exp = (f.exposure.get(e.id) ?? 0) + sim.dt;
    f.exposure.set(e.id, exp);
    if (exp < spec.exposure_s) continue;
    f.rolled.add(e.id);
    if (!sim.rng.effect.chance(p)) continue;
    f.affected.add(e.id);
    if (spec.kind === "rf_jam") sim.linkLost(e, f);
    else sim.divert(e, f);
  }
  if (sim.t >= f.until) {
    const hit = f.targetEntity !== null && f.affected.has(f.targetEntity);
    finish(sim, f, hit ? (spec.kind === "rf_jam" ? "link_lost" : "diverted") : "no_effect");
  }
}

function runLaser(sim: Sim, f: EffectorState): void {
  const e = f.targetEntity ? sim.byId.get(f.targetEntity) : undefined;
  if (!e || !e.flying || e.phase === "falling") return finish(sim, f, "target_gone");
  const wx = sim.weatherFx();
  const ok = dist(f.pos, e.pos) <= f.spec.range_m && sim.terrain.los(f.pos, e.pos) && wx.laser_ok;
  if (!ok) {
    f.outOfRangeSince ??= sim.t;
    if (sim.t - f.outOfRangeSince > BREAK_LOCK_S) finish(sim, f, "broke_lock");
    return;
  }
  f.outOfRangeSince = null;
  f.dwell += sim.dt;
  const need = f.spec.dwell_s * (sim.cat.laser_dwell[e.cls] ?? 1) * wx.laser_dwell;
  sim.beam(f, e.pos);
  if (f.dwell >= need) {
    sim.neutralise(e, f);
    finish(sim, f, "kill");
  }
}

function runGun(sim: Sim, f: EffectorState): void {
  const e = f.targetEntity ? sim.byId.get(f.targetEntity) : undefined;
  const tr = sim.trackById.get(f.targetTrack ?? "");
  if (!e || !tr || !e.flying || e.phase === "falling" || tr.down) return finish(sim, f, e && e.outcome === "neutralised" && e.outcomeBy === f.id ? "kill" : "target_gone");
  if (sim.t < f.nextShotT) return;
  const est = sim.predicted(tr);
  const r = dist(f.pos, est);
  if (!tr.displayed || r > f.spec.range_m || !sim.terrain.los(f.pos, est)) {
    f.outOfRangeSince ??= sim.t;
    if (sim.t - f.outOfRangeSince > BREAK_LOCK_S) finish(sim, f, "broke_lock");
    return;
  }
  f.outOfRangeSince = null;
  if (f.ammo !== null && f.ammo < f.spec.rounds_per_shot) return finish(sim, f, "out_of_ammo");
  if (f.ammo !== null) f.ammo -= f.spec.rounds_per_shot;
  charge(sim, f, f.spec.cost_inr * f.spec.rounds_per_shot);
  f.nextShotT = sim.t + f.spec.cycle_s;
  if (!f.collateralLogged && sim.inNoFireZone(est)) {
    f.collateralLogged = true;
    sim.collateral(f, tr, est);
  }
  const sizeF = Math.min(1, Math.sqrt(e.spec.size_m / 0.5));
  const speedF = Math.max(0.4, 1 - Math.max(0, Math.hypot(e.vel.x, e.vel.y) - 15) / 60);
  const pk = f.spec.pk * (sim.cat.effect_matrix.gun?.[e.cls] ?? 1) * (1 - Math.pow(r / f.spec.range_m, 2)) * sizeF * speedF;
  sim.projectiles.push(mkProjectile(sim, f, tr, e, est, r, pk));
}

function launch(sim: Sim, f: EffectorState, tr: Track, target: Entity): void {
  const spec = f.spec;
  const est = sim.predicted(tr);
  const r = dist(f.pos, est);
  if (spec.kind === "rocket") {
    // aim at the predicted intercept point from the TRACK (track error matters)
    let aim = est;
    for (let i = 0; i < 2; i++) aim = add(est, scale(tr.vel, dist(f.pos, aim) / spec.speed_mps));
    for (let k = 0; k < spec.rounds_per_shot; k++) {
      const a = v3(aim.x + sim.rng.effect.gauss() * 6, aim.y + sim.rng.effect.gauss() * 6, aim.z + sim.rng.effect.gauss() * 4);
      sim.projectiles.push({ ...mkProjectile(sim, f, tr, null, a, dist(f.pos, a), spec.pk), blast: spec.blast_m });
    }
    if (sim.inNoFireZone(aim) && !f.collateralLogged) {
      f.collateralLogged = true;
      sim.collateral(f, tr, aim);
    }
  } else {
    sim.projectiles.push(mkProjectile(sim, f, tr, target, est, r, spec.pk * (sim.cat.effect_matrix[spec.kind]?.[target.cls] ?? 1)));
  }
  if (f.ammo !== null) f.ammo -= spec.rounds_per_shot;
  charge(sim, f, spec.cost_inr * spec.rounds_per_shot);
}

function mkProjectile(sim: Sim, f: EffectorState, tr: Track, e: Entity | null, aim: Vec3, r: number, pk: number): Projectile {
  return {
    kind: f.spec.kind,
    effectorId: f.id,
    orderId: f.orderId,
    trackId: tr.id,
    targetEntity: e?.id ?? null,
    from: f.pos,
    aim,
    fireT: sim.t,
    impactT: sim.t + r / Math.max(1, f.spec.speed_mps),
    pk,
    blast: 0,
  };
}

function runProjectiles(sim: Sim): void {
  const done: Projectile[] = [];
  for (const p of sim.projectiles) {
    if (sim.t < p.impactT) continue;
    done.push(p);
    const f = sim.effectors.find((x) => x.id === p.effectorId)!;
    let killed = false;
    if (p.kind === "rocket") {
      for (const e of sim.entities) {
        if (!e.flying || e.phase === "falling" || dist(e.pos, p.aim) > p.blast) continue;
        if (sim.rng.effect.chance(p.pk * (sim.cat.effect_matrix.rocket?.[e.cls] ?? 1))) {
          sim.neutralise(e, f);
          if (e.id === f.targetEntity || e.trackId === p.trackId) killed = true;
          else killed = killed || false;
        }
      }
    } else {
      const e = p.targetEntity ? sim.byId.get(p.targetEntity) : undefined;
      const reach = p.kind === "gun" ? f.spec.range_m * 1.05 : f.spec.range_m * 1.15;
      if (e && e.flying && e.phase !== "falling" && dist2(f.pos, e.pos) <= reach && sim.rng.effect.chance(p.pk)) {
        sim.neutralise(e, f);
        killed = true;
      }
    }
    sim.tracer(p);
    const outstanding = sim.projectiles.some((q) => q !== p && q.orderId === p.orderId && !done.includes(q));
    if (p.kind !== "gun" && !outstanding && f.orderId === p.orderId && (f.status === "active" || f.status === "slewing")) {
      const tgt = p.targetEntity ? sim.byId.get(p.targetEntity) : f.targetEntity ? sim.byId.get(f.targetEntity) : undefined;
      finish(sim, f, killed || (tgt && tgt.outcome === "neutralised" && tgt.outcomeBy === f.id) ? "kill" : "miss");
    }
  }
  if (done.length) sim.projectiles = sim.projectiles.filter((p) => !done.includes(p));
}
