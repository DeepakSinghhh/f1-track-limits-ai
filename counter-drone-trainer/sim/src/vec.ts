/** Minimal 3D vector maths. x east, y north, z up (metres). */
export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export const v3 = (x = 0, y = 0, z = 0): Vec3 => ({ x, y, z });
export const add = (a: Vec3, b: Vec3): Vec3 => v3(a.x + b.x, a.y + b.y, a.z + b.z);
export const sub = (a: Vec3, b: Vec3): Vec3 => v3(a.x - b.x, a.y - b.y, a.z - b.z);
export const scale = (a: Vec3, k: number): Vec3 => v3(a.x * k, a.y * k, a.z * k);
export const dot = (a: Vec3, b: Vec3): number => a.x * b.x + a.y * b.y + a.z * b.z;
export const len = (a: Vec3): number => Math.hypot(a.x, a.y, a.z);
export const len2 = (a: Vec3): number => Math.hypot(a.x, a.y);
export const dist = (a: Vec3, b: Vec3): number => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
export const dist2 = (a: Vec3, b: Vec3): number => Math.hypot(a.x - b.x, a.y - b.y);
export const copy = (a: Vec3): Vec3 => v3(a.x, a.y, a.z);

export function norm(a: Vec3): Vec3 {
  const l = len(a);
  return l > 1e-9 ? scale(a, 1 / l) : v3();
}

export function clampLen(a: Vec3, max: number): Vec3 {
  const l = len(a);
  return l > max ? scale(a, max / l) : a;
}

export const DEG = Math.PI / 180;

/** Bearing from a to b, degrees clockwise from north, in [0, 360). */
export function bearing(a: Vec3, b: Vec3): number {
  const deg = Math.atan2(b.x - a.x, b.y - a.y) / DEG;
  return (deg + 360) % 360;
}

/** Elevation angle from a to b in degrees. */
export function elevation(a: Vec3, b: Vec3): number {
  return Math.atan2(b.z - a.z, dist2(a, b)) / DEG;
}

/** Point at `range` metres along `bearingDeg` from `origin` (same z). */
export function polar(origin: Vec3, bearingDeg: number, range: number): Vec3 {
  return v3(origin.x + Math.sin(bearingDeg * DEG) * range, origin.y + Math.cos(bearingDeg * DEG) * range, origin.z);
}

/** Smallest signed difference a-b in degrees, in (-180, 180]. */
export function angleDiff(a: number, b: number): number {
  let d = (a - b) % 360;
  if (d > 180) d -= 360;
  if (d <= -180) d += 360;
  return d;
}

export const clamp = (x: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, x));
