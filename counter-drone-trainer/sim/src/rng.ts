/**
 * Seeded PRNG (mulberry32) with named streams (PLAN.md 4.3).
 *
 * Each subsystem draws from its own stream, so adding a bird to a scenario
 * changes the bird stream only: radar noise, Pk rolls and spawn jitter for
 * everything else stay identical for the same seed.
 */
export class Rng {
  private s: number;

  constructor(seed: number) {
    this.s = seed >>> 0;
  }

  /** Uniform in [0, 1). */
  next(): number {
    this.s = (this.s + 0x6d2b79f5) >>> 0;
    let t = this.s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  range(a: number, b: number): number {
    return a + (b - a) * this.next();
  }

  /** Integer in [a, b] inclusive. */
  int(a: number, b: number): number {
    return Math.floor(this.range(a, b + 1));
  }

  chance(p: number): boolean {
    return this.next() < p;
  }

  pick<T>(items: readonly T[]): T {
    return items[Math.floor(this.next() * items.length)];
  }

  /** Standard normal (Box-Muller). */
  gauss(): number {
    const u = Math.max(this.next(), 1e-12);
    const v = this.next();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }
}

/** FNV-1a hash of a stream name mixed with the scenario seed. */
export function streamSeed(seed: number, name: string): number {
  let h = 0x811c9dc5 ^ (seed >>> 0);
  for (let i = 0; i < name.length; i++) {
    h ^= name.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13;
  return h >>> 0;
}

export function streams(seed: number) {
  return {
    terrain: new Rng(streamSeed(seed, "terrain")),
    spawn: new Rng(streamSeed(seed, "spawn")),
    behaviour: new Rng(streamSeed(seed, "behaviour")),
    birds: new Rng(streamSeed(seed, "birds")),
    radar: new Rng(streamSeed(seed, "radar")),
    rf: new Rng(streamSeed(seed, "rf")),
    acoustic: new Rng(streamSeed(seed, "acoustic")),
    effect: new Rng(streamSeed(seed, "effect")),
  };
}

export type Streams = ReturnType<typeof streams>;
