/**
 * Sensor models (PLAN.md 6.4). Each sensor has the weakness the PS calls out,
 * modelled explicitly:
 *  - radar: Pd falls with range and RCS; the MTI filter drops targets whose
 *    radial speed is below a floor (hovering drones, tangential flight);
 *    birds have drone-sized RCS and become tracks; terrain masks low flyers.
 *  - RF: sees only emitters, bearing only; fiber-optic and pre-programmed
 *    drones are invisible to it.
 *  - acoustic: bearing only, short range, drowned by ambient noise.
 *  - IFF: friendly transponders reply; everything else does not (birds too).
 *  - EO/IR camera: see camera.ts.
 */
import type { Sim } from "./sim.ts";
import type { Entity, SensorState } from "./types.ts";
import { add, bearing, clamp, DEG, dist, dot, norm, sub, v3, type Vec3 } from "./vec.ts";

export function runSensors(sim: Sim): void {
  for (const s of sim.sensors) {
    if (s.status === "down" || sim.t < s.nextUpdate) continue;
    s.nextUpdate = sim.t + s.spec.update_s;
    switch (s.type) {
      case "radar":
        radarScan(sim, s);
        break;
      case "rf":
        rfScan(sim, s);
        break;
      case "acoustic":
        acousticScan(sim, s);
        break;
      case "iff":
        iffScan(sim, s);
        break;
      default:
        break;
    }
  }
}

function radarScan(sim: Sim, s: SensorState): void {
  const p = s.spec.params;
  const rng = sim.rng.radar;
  const wx = sim.weatherFx();
  const degraded = s.status === "degraded";
  for (const e of sim.entities) {
    if (!e.flying) continue;
    const r = dist(s.pos, e.pos);
    if (r > s.spec.range_m || r < 30) continue;
    const los = norm(sub(e.pos, s.pos));
    const radial = Math.abs(dot(e.vel, los));
    if (radial < (p.mti_mps ?? 1.5)) continue; // MTI: filtered as clutter
    if (!sim.terrain.los(s.pos, e.pos)) continue;
    const rcs = e.spec.rcs_m2 * (0.4 + 1.2 * rng.next());
    const r50 = (p.r1_m ?? 8000) * Math.pow(rcs, 0.25) * wx.radar * (degraded ? 0.6 : 1);
    const pd = 1 / (1 + Math.pow(r / r50, 6));
    if (!rng.chance(pd)) continue;
    const k = degraded ? 2.5 : 1;
    const az = bearing(s.pos, e.pos) + rng.gauss() * (p.sigma_az_deg ?? 0.4) * k;
    const el = Math.atan2(e.pos.z - s.pos.z, Math.hypot(e.pos.x - s.pos.x, e.pos.y - s.pos.y)) / DEG + rng.gauss() * (p.sigma_el_deg ?? 0.8) * k;
    const rr = r + rng.gauss() * (p.sigma_range_m ?? 10) * k;
    sim.fix(e, "radar", fromSpherical(s.pos, az, el, rr));
  }
}

function rfScan(sim: Sim, s: SensorState): void {
  const p = s.spec.params;
  const rng = sim.rng.rf;
  for (const e of sim.entities) {
    if (!e.flying || e.spec.link !== "rf" || e.linkLost) continue;
    const r = dist(s.pos, e.pos);
    if (r > s.spec.range_m * (s.status === "degraded" ? 0.5 : 1)) continue;
    if (!rng.chance(p.pd ?? 0.9)) continue;
    const brg = bearing(s.pos, e.pos) + rng.gauss() * (p.sigma_az_deg ?? 3);
    sim.strobe(e, "rf", s.pos, brg, e.spec.rf_band ?? null);
  }
}

function acousticScan(sim: Sim, s: SensorState): void {
  const p = s.spec.params;
  const rng = sim.rng.acoustic;
  const ambient = sim.sc.environment.ambient_noise_db + sim.weatherFx().ambient_db + (s.status === "degraded" ? 10 : 0);
  for (const e of sim.entities) {
    if (!e.flying || e.spec.acoustic_db <= 0) continue;
    const reach = Math.min(s.spec.range_m, (p.ref_m ?? 10) * Math.pow(10, (e.spec.acoustic_db - ambient) / 20));
    const r = dist(s.pos, e.pos);
    if (r > reach) continue;
    if (!rng.chance(p.pd ?? 0.8)) continue;
    const brg = bearing(s.pos, e.pos) + rng.gauss() * (p.sigma_az_deg ?? 6);
    sim.strobe(e, "ac", s.pos, brg, null);
  }
}

function iffScan(sim: Sim, s: SensorState): void {
  for (const tr of sim.tracks) {
    if (!tr.displayed) continue;
    const e = sim.byId.get(tr.entityId)!;
    if (dist(s.pos, tr.est) > s.spec.range_m) continue;
    tr.iff = e.iff && e.flying && !e.linkLost ? "friend" : "no_reply";
  }
}

export function fromSpherical(origin: Vec3, azDeg: number, elDeg: number, range: number): Vec3 {
  const h = range * Math.cos(elDeg * DEG);
  return add(origin, v3(Math.sin(azDeg * DEG) * h, Math.cos(azDeg * DEG) * h, range * Math.sin(elDeg * DEG)));
}

/** Sensor down/degraded windows from the scenario, with state-change events. */
export function updateSensorStatus(sim: Sim): void {
  for (const s of sim.sensors) {
    const placement = sim.sc.sensors[s.idx];
    let status: SensorState["status"] = "ok";
    for (const ev of placement.events) {
      if (sim.t >= ev.t && sim.t < ev.t + ev.for_s) status = ev.state;
    }
    if (status !== s.status) {
      s.status = status;
      sim.emit("sensor_state", { data: { sensor: s.id, type: s.type, state: status } });
      sim.say(
        `${s.spec.name.toUpperCase()} ${status === "ok" ? "RESTORED" : status.toUpperCase()}`,
        status === "ok" ? "good" : "alert",
      );
      if (s.type === "iff" && status === "down") for (const tr of sim.tracks) if (tr.iff === "friend" || tr.iff === "no_reply") tr.iff = "unavailable";
    }
  }
}

/** Rough "how visible is this in the camera" check used for designation. */
export function cameraCanSee(sim: Sim, e: Entity, from: Vec3): { ok: boolean; reason?: string } {
  const wx = sim.weatherFx();
  const r = dist(from, e.pos);
  const tod = sim.sc.environment.time_of_day;
  const light = tod === "day" ? 1 : tod === "dusk" ? 0.55 : 0.12;
  const vis =
    sim.camera.mode === "eo" ? wx.eo_vis_km * 1000 * light : wx.ir_vis_km * 1000 * (0.5 + 0.7 * e.spec.thermal);
  if (r > vis) return { ok: false, reason: sim.camera.mode === "eo" && light < 0.5 ? "too dark for EO, try IR" : "beyond visibility" };
  const px = (e.spec.size_m / (2 * r * Math.tan((sim.camera.fov * DEG) / 2))) * 640;
  if (px < (sim.camera.mode === "ir" ? 0.8 : 1.5)) return { ok: false, reason: "too small at this zoom" };
  if (!sim.terrain.los(from, e.pos)) return { ok: false, reason: "masked by terrain" };
  return { ok: true };
}

export const clampFov = (sim: Sim, fov: number): number => {
  const p = sim.cameraSpec().params;
  return clamp(fov, p.fov_min_deg ?? 0.5, p.fov_max_deg ?? 30);
};
