import type { Bar } from "./types";
import type { Timeframe } from "./usePriceBars";

const INTERVAL_NS: Record<Timeframe, number> = {
  "1m": 60e9,
  "5m": 300e9,
  "15m": 900e9,
  "1h": 3600e9,
  "1d": 86_400e9,
};

/**
 * Indexes of bars that follow a gap in time. Bars are drawn side by side with no
 * empty slots, so gaps would otherwise be invisible. Session opens at 6pm ET count too.
 */
export function breaksBefore(bars: Bar[], timeframe: Timeframe): { index: number; session: boolean }[] {
  if (timeframe === "1d") return [];
  const step = INTERVAL_NS[timeframe];
  const result: { index: number; session: boolean }[] = [];
  for (let index = 1; index < bars.length; index++) {
    const previous = bars[index - 1];
    const bar = bars[index];
    if (!previous || !bar) continue;
    const gap = bar.start_ns - previous.start_ns;
    const opens = new Date(bar.start_ns / 1e6).toLocaleString("en-US", {
      hour: "numeric",
      hour12: false,
      timeZone: "America/New_York",
    });
    const session = gap >= 3_600e9 && opens === "18";
    if (session || gap > step * 3) result.push({ index, session });
  }
  return result;
}
