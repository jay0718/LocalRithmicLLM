import type { EquityOverlay } from "./useEquityOverlay";
import type { GexSnapshot, StrikeGex } from "./types";

export type OverlayMode = "off" | "overlay" | "combined";

/** The ETF's GEX summed into the futures chart's buckets, with the dealer sign convention applied. */
export function bucketOverlay(overlay: EquityOverlay, size: number, flip: boolean): Map<number, StrikeGex> {
  const sign = flip ? -1 : 1;
  const buckets = new Map<number, StrikeGex>();
  for (const row of overlay.strikes) {
    const key = Math.round(row.strike / size) * size;
    const total = buckets.get(key) ?? { strike: key, call_gex: 0, put_gex: 0, net_gex: 0 };
    total.call_gex += sign * row.call_gex;
    total.put_gex += sign * row.put_gex;
    total.net_gex += sign * row.net_gex;
    buckets.set(key, total);
  }
  return buckets;
}

/**
 * Adds empty futures rows wherever only the ETF has gamma, so overlay bars have a row to sit on.
 * With combine, each row also takes the ETF's GEX and the walls are recomputed on the sum.
 */
export function withOverlay(
  profile: GexSnapshot,
  buckets: Map<number, StrikeGex>,
  combine: boolean,
): GexSnapshot {
  const rows = new Map(profile.strikes.map((row) => [row.strike, { ...row }]));
  for (const [strike, extra] of buckets) {
    const row = rows.get(strike) ?? { strike, call_gex: 0, put_gex: 0, net_gex: 0 };
    if (combine) {
      row.call_gex += extra.call_gex;
      row.put_gex += extra.put_gex;
      row.net_gex += extra.net_gex;
    }
    rows.set(strike, row);
  }
  const strikes = [...rows.values()].sort((a, b) => a.strike - b.strike);
  if (!combine) return { ...profile, strikes };
  const best = (score: (row: StrikeGex) => number) =>
    strikes.reduce<StrikeGex | null>(
      (top, row) => (top === null || score(row) > score(top) ? row : top),
      null,
    );
  const call = best((row) => row.net_gex);
  const put = best((row) => -row.net_gex);
  const king = best((row) => Math.abs(row.net_gex));
  const extraTotal = [...buckets.values()].reduce((sum, row) => sum + row.net_gex, 0);
  return {
    ...profile,
    strikes,
    total_gex: profile.total_gex + extraTotal,
    call_wall: call && call.net_gex > 0 ? call.strike : null,
    put_wall: put && put.net_gex < 0 ? put.strike : null,
    king_node: king?.strike ?? null,
    king_node_gex: king?.net_gex ?? null,
  };
}
