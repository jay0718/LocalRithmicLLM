import type { components } from "../../api/gex";

export type GexSnapshot = components["schemas"]["GexSnapshot"];
export type StrikeGex = components["schemas"]["StrikeGex"];
export type Convention = GexSnapshot["convention"];
export type Bar = components["schemas"]["Bar"];
export type LiveUpdate = components["schemas"]["LiveUpdate"];
export type Underlying = components["schemas"]["UnderlyingOut"];

/**
 * Flipping the dealer assumption negates every exposure. The flip level and the
 * walls (largest absolute exposure) are unchanged, so this is exact on the client.
 */
export function withConvention(snapshot: GexSnapshot, convention: Convention): GexSnapshot {
  if (convention === snapshot.convention) return snapshot;
  return {
    ...snapshot,
    convention,
    total_gex: -snapshot.total_gex,
    king_node_gex: snapshot.king_node_gex === null ? null : -snapshot.king_node_gex,
    strikes: snapshot.strikes.map((row) => ({
      strike: row.strike,
      call_gex: -row.call_gex,
      put_gex: -row.put_gex,
      net_gex: -row.net_gex,
    })),
  };
}

/** The strikes nearest spot, count on each side, in descending order. */
export function strikesAround(snapshot: GexSnapshot, eachSide: number): StrikeGex[] {
  const rows = [...snapshot.strikes].sort((a, b) => a.strike - b.strike);
  if (rows.length === 0) return [];
  let center = 0;
  rows.forEach((row, index) => {
    const best = rows[center];
    if (best && Math.abs(row.strike - snapshot.spot) < Math.abs(best.strike - snapshot.spot)) center = index;
  });
  return rows.slice(Math.max(center - eachSide, 0), center + eachSide + 1).reverse();
}

const BUCKET_CHOICES = [5, 10, 25, 50, 100, 200, 250, 500, 1000];

/** The smallest gap between listed strikes. */
export function nativeStep(snapshot: GexSnapshot): number {
  const strikes = [...new Set(snapshot.strikes.map((row) => row.strike))].sort((a, b) => a - b);
  const gaps = strikes.slice(1).map((strike, index) => strike - (strikes[index] ?? strike));
  return gaps.length ? Math.min(...gaps) : 1;
}

/** Bucket sizes worth offering: native strikes, then wider round sizes up to 40 strikes per bucket. */
export function bucketChoices(step: number): number[] {
  return [step, ...BUCKET_CHOICES.filter((size) => size > step && size <= step * 40 && size % step === 0)];
}

/** A default bucket of roughly 0.4% of price, which reads well at ±20 rows. */
export function defaultBucket(step: number, spot: number): number {
  const target = spot * 0.004;
  return bucketChoices(step).reduce((best, size) =>
    Math.abs(size - target) < Math.abs(best - target) ? size : best,
  );
}

/**
 * Sum exposure into buckets centered on multiples of size. Levels keep their exact
 * strikes elsewhere; here they move to the bucket that contains them so the
 * profile can highlight it.
 */
export function groupStrikes(snapshot: GexSnapshot, size: number): GexSnapshot {
  if (size <= nativeStep(snapshot)) return snapshot;
  const key = (strike: number) => Math.round(strike / size) * size;
  const buckets = new Map<number, StrikeGex>();
  for (const row of snapshot.strikes) {
    const bucket = key(row.strike);
    const total = buckets.get(bucket) ?? { strike: bucket, call_gex: 0, put_gex: 0, net_gex: 0 };
    total.call_gex += row.call_gex;
    total.put_gex += row.put_gex;
    total.net_gex += row.net_gex;
    buckets.set(bucket, total);
  }
  const map = (level: number | null) => (level === null ? null : key(level));
  return {
    ...snapshot,
    strikes: [...buckets.values()].sort((a, b) => a.strike - b.strike),
    call_wall: map(snapshot.call_wall),
    put_wall: map(snapshot.put_wall),
    king_node: map(snapshot.king_node),
  };
}
