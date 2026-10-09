import { Rng } from "./rng.ts";
import { clamp, dist2, type Vec3 } from "./vec.ts";

/**
 * Procedural heightmap (generic terrain, never a real installation's layout:
 * PLAN.md non-negotiable 3). "foothills" rises towards the north, like the
 * terrain around northern airbases; "plains" is gently rolling. The ground is
 * flattened around defended assets so the base sits on level ground at z = 0.
 */
export class Terrain {
  readonly n = 129;
  readonly size: number;
  readonly cell: number;
  readonly h: Float32Array;
  readonly maxH: number;

  constructor(seed: number, kind: "plains" | "foothills", size: number, flat: { x: number; y: number; r: number }[]) {
    this.size = size;
    this.cell = size / (this.n - 1);
    this.h = new Float32Array(this.n * this.n);
    const rng = new Rng(seed);
    const octaves = [
      { grid: 5, amp: 1.0 },
      { grid: 9, amp: 0.5 },
      { grid: 17, amp: 0.25 },
      { grid: 33, amp: 0.12 },
    ].map((o) => ({ ...o, v: Float32Array.from({ length: o.grid * o.grid }, () => rng.next()) }));
    const baseAmp = kind === "foothills" ? 260 : 45;
    let maxH = 0;
    for (let j = 0; j < this.n; j++) {
      for (let i = 0; i < this.n; i++) {
        const u = i / (this.n - 1);
        const w = j / (this.n - 1);
        let hgt = 0;
        for (const o of octaves) hgt += o.amp * valueNoise(o.v, o.grid, u, w);
        hgt = (hgt / 1.87) * baseAmp;
        if (kind === "foothills") hgt *= 0.35 + 1.3 * smooth(clamp((w - 0.35) / 0.65, 0, 1));
        const x = -size / 2 + i * this.cell;
        const y = -size / 2 + j * this.cell;
        let f = 1;
        for (const z of flat) f = Math.min(f, smooth(clamp((dist2({ x, y, z: 0 }, { x: z.x, y: z.y, z: 0 }) - z.r) / (z.r * 2.5), 0, 1)));
        hgt *= f;
        this.h[j * this.n + i] = hgt;
        maxH = Math.max(maxH, hgt);
      }
    }
    this.maxH = maxH;
  }

  /** Bilinear ground height at (x, y); 0 outside the map. */
  height(x: number, y: number): number {
    const fx = (x + this.size / 2) / this.cell;
    const fy = (y + this.size / 2) / this.cell;
    if (fx < 0 || fy < 0 || fx >= this.n - 1 || fy >= this.n - 1) return 0;
    const i = Math.floor(fx);
    const j = Math.floor(fy);
    const tx = fx - i;
    const ty = fy - j;
    const a = this.h[j * this.n + i];
    const b = this.h[j * this.n + i + 1];
    const c = this.h[(j + 1) * this.n + i];
    const d = this.h[(j + 1) * this.n + i + 1];
    return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty;
  }

  /** True if the straight line a-b clears the terrain (2 m margin). */
  los(a: Vec3, b: Vec3): boolean {
    const d = dist2(a, b);
    const steps = Math.max(2, Math.ceil(d / (this.cell * 0.5)));
    for (let s = 1; s < steps; s++) {
      const t = s / steps;
      const x = a.x + (b.x - a.x) * t;
      const y = a.y + (b.y - a.y) * t;
      const z = a.z + (b.z - a.z) * t;
      if (this.height(x, y) + 2 > z) return false;
    }
    return true;
  }
}

function smooth(t: number): number {
  return t * t * (3 - 2 * t);
}

function valueNoise(v: Float32Array, grid: number, u: number, w: number): number {
  const fx = u * (grid - 1);
  const fy = w * (grid - 1);
  const i = Math.min(grid - 2, Math.floor(fx));
  const j = Math.min(grid - 2, Math.floor(fy));
  const tx = smooth(fx - i);
  const ty = smooth(fy - j);
  const a = v[j * grid + i];
  const b = v[j * grid + i + 1];
  const c = v[(j + 1) * grid + i];
  const d = v[(j + 1) * grid + i + 1];
  return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty;
}
