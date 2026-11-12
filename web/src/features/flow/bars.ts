import type { Bar } from "./useFlowHistory";

const MINUTE = 60_000_000_000;

/** Combine one-minute bars into ``minutes``-long candles aligned to the clock. */
export function combine(bars: Bar[], minutes: number): Bar[] {
  if (minutes <= 1) return bars;
  const size = minutes * MINUTE;
  const out: Bar[] = [];
  for (const bar of bars) {
    const start = Math.floor(bar.start_ns / size) * size;
    const last = out.at(-1);
    if (last && last.start_ns === start) {
      last.high = Math.max(last.high, bar.high);
      last.low = Math.min(last.low, bar.low);
      last.close = bar.close;
      last.volume += bar.volume;
    } else out.push({ ...bar, start_ns: start });
  }
  return out;
}

/** Index of the last frame at or before ``ns`` (-1 if none), by binary search over sorted frames. */
export function frameAt(frames: { ts_ns: number }[], ns: number): number {
  let low = 0;
  let high = frames.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if ((frames[mid]?.ts_ns ?? Infinity) <= ns) {
      found = mid;
      low = mid + 1;
    } else high = mid - 1;
  }
  return found;
}
