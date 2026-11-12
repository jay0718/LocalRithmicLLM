import type { EquityOverlay } from "./useEquityOverlay";
import type { GexSnapshot } from "./types";

export function makeSnapshot(overrides: Partial<GexSnapshot> = {}): GexSnapshot {
  const strikes = [5950, 5975, 6000, 6025, 6050].map((strike, index) => {
    const call_gex = [0.1e9, 0.2e9, 0.6e9, 1.2e9, 0.4e9][index] ?? 0;
    const put_gex = [-0.9e9, -0.7e9, -0.5e9, -0.1e9, 0][index] ?? 0;
    return { strike, call_gex, put_gex, net_gex: call_gex + put_gex };
  });
  return {
    data_source: "synthetic",
    underlying: "ESZ6",
    spot: 6006.25,
    as_of_ns: 1_794_000_000_000_000_000,
    convention: "long_calls_short_puts",
    expiry: null,
    total_gex: strikes.reduce((sum, row) => sum + row.net_gex, 0),
    flip_level: 5990.5,
    call_wall: 6025,
    put_wall: 5950,
    king_node: 6025,
    king_node_gex: 1.1e9,
    strikes,
    contracts_total: 486,
    contracts_used: 478,
    missing_quotes: 0,
    stale_quotes: 3,
    missing_open_interest: 0,
    unpriced: 5,
    priced_from_settlement: 0,
    expiries: ["20261112", "20261113"],
    oldest_settlement: null,
    ...overrides,
  };
}

export const EMPTY_SNAPSHOT = makeSnapshot({
  strikes: [],
  total_gex: 0,
  flip_level: null,
  call_wall: null,
  put_wall: null,
  king_node: null,
  king_node_gex: null,
  contracts_used: 0,
});

export const OVERLAY: EquityOverlay = {
  symbol: "SPY",
  trade_date: "20261111",
  source_close: 600.6,
  target_close: 6006,
  ratio: 10,
  ratio_basis: "close",
  expiries: ["20261112", "20261113"],
  total_gex: -1e9,
  call_wall: 6000,
  put_wall: 5975,
  king_node: 5975,
  flip_level: null,
  contracts_used: 4,
  contracts_total: 4,
  prices_missing: 0,
  prices_pending: 0,
  series_total: 4,
  open_interest_source: "OCC",
  strikes: [
    { strike: 5972, source_strike: 597.2, call_gex: 0, put_gex: -3e9, net_gex: -3e9 },
    { strike: 6001, source_strike: 600.1, call_gex: 1.5e9, put_gex: 0, net_gex: 1.5e9 },
    { strike: 6004, source_strike: 600.4, call_gex: 0.5e9, put_gex: 0, net_gex: 0.5e9 },
    { strike: 6100, source_strike: 610, call_gex: 0.1e9, put_gex: -0.1e9, net_gex: 0 },
  ],
};
