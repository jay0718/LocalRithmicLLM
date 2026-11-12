import type { StrikeGex } from "./types";

export const ROW = 18;
/** Rows never get thinner than this, however many strikes are shown. */
export const MIN_ROW = 7;
export const SCALE_TOP = 28;
export const SCALE_BOTTOM = 8;

export type PriceScale = {
  top: number;
  bottom: number;
  step: number;
  /** Pixel height of one strike row (0 for a fitted scale). */
  row: number;
  height: number;
  y: (price: number) => number;
  contains: (price: number) => boolean;
};

/**
 * A linear price axis shared by the GEX profile and the price chart, so a level
 * sits at the same height in both. One strike step is one row.
 */
export function makePriceScale(rows: StrikeGex[], maxHeight = Infinity): PriceScale | null {
  if (rows.length === 0) return null;
  const strikes = rows.map((row) => row.strike).sort((a, b) => a - b);
  const top = strikes.at(-1) ?? 0;
  const bottom = strikes[0] ?? 0;
  const gaps = strikes
    .slice(1)
    .map((strike, index) => strike - (strikes[index] ?? strike))
    .filter((gap) => gap > 0);
  const step = gaps.length ? Math.min(...gaps) : 1;
  const span = (top - bottom) / step + 1;
  // Shrink rows so the whole chart fits in maxHeight, down to a readable minimum.
  const row = Math.max(MIN_ROW, Math.min(ROW, (maxHeight - SCALE_TOP - SCALE_BOTTOM) / span));
  const pxPerPoint = row / step;
  const y = (price: number) => SCALE_TOP + row / 2 + (top - price) * pxPerPoint;
  const half = step / 2;
  return {
    top,
    bottom,
    step,
    row,
    height: SCALE_TOP + span * row + SCALE_BOTTOM,
    y,
    contains: (price) => price <= top + half && price >= bottom - half,
  };
}

/** Round, evenly spaced price ticks between min and max. */
export function niceTicks(min: number, max: number, target = 5): number[] {
  const span = max - min;
  if (!(span > 0)) return [min];
  const rough = span / target;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = ([1, 2, 2.5, 5, 10].find((m) => m * magnitude >= rough) ?? 10) * magnitude;
  const ticks: number[] = [];
  for (let tick = Math.ceil(min / step) * step; tick <= max + step / 1e6; tick += step)
    ticks.push(Number(tick.toFixed(10)));
  return ticks;
}

/**
 * A price axis fitted to the candles, for when price moves too little to see on the
 * strike scale. Uses the same height as the strike scale so the panels stay level.
 */
export function makeFitScale(
  lows: number[],
  highs: number[],
  height: number,
  minSpan: number,
): PriceScale | null {
  if (lows.length === 0) return null;
  let low = Math.min(...lows);
  let high = Math.max(...highs);
  if (high - low < minSpan) {
    const middle = (high + low) / 2;
    low = middle - minSpan / 2;
    high = middle + minSpan / 2;
  }
  const pad = (high - low) * 0.08;
  low -= pad;
  high += pad;
  const plotTop = SCALE_TOP;
  const plotHeight = height - SCALE_TOP - SCALE_BOTTOM;
  return {
    top: high,
    bottom: low,
    step: 0,
    row: 0,
    height,
    y: (price) => plotTop + ((high - price) / (high - low)) * plotHeight,
    contains: (price) => price <= high && price >= low,
  };
}

/**
 * Spread label positions so no two are closer than gap, keeping their order.
 * Returns adjusted y values in the same order as the input.
 */
export function spreadLabels(ys: number[], gap = 13): number[] {
  const order = ys.map((y, index) => ({ y, index })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < order.length; i++) {
    const previous = order[i - 1];
    const current = order[i];
    if (previous && current && current.y - previous.y < gap) current.y = previous.y + gap;
  }
  const result = [...ys];
  for (const item of order) result[item.index] = item.y;
  return result;
}
