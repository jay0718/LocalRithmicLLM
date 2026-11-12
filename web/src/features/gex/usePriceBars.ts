import { useEffect, useRef, useState } from "react";
import type { Bar } from "./types";

export type Timeframe = "1m" | "5m" | "15m" | "1h" | "1d";

export const TIMEFRAMES: { value: Timeframe; label: string; limit: number }[] = [
  { value: "1m", label: "1m", limit: 5000 },
  { value: "5m", label: "5m", limit: 3000 },
  { value: "15m", label: "15m", limit: 1000 },
  { value: "1h", label: "1h", limit: 400 },
  { value: "1d", label: "1D", limit: 60 },
];

/**
 * Within the minute still forming, the live bar can only extend the latest bar's
 * range and move its close. Volume and new bars come from a refetch.
 */
export function applyLiveMinute(bars: Bar[], minute: Bar): Bar[] {
  const last = bars.at(-1);
  if (!last || minute.start_ns < last.start_ns) return bars;
  return [
    ...bars.slice(0, -1),
    {
      ...last,
      high: Math.max(last.high, minute.high),
      low: Math.min(last.low, minute.low),
      close: minute.close,
    },
  ];
}

type State = { bars: Bar[]; loading: boolean; error: string | null; key: string };

/**
 * Bar history for a symbol and timeframe. Reloads when either changes, after
 * every reconnect, and whenever a new minute starts; between reloads the live
 * minute bar keeps the latest bar current.
 */
export function usePriceBars(
  underlying: string,
  timeframe: Timeframe,
  liveBar: Bar | null,
  connection: number,
) {
  const key = `${underlying}|${timeframe}`;
  const [state, setState] = useState<State>({ bars: [], loading: true, error: null, key });
  if (state.key !== key) setState({ bars: [], loading: true, error: null, key });

  const minuteStart = liveBar?.start_ns ?? null;
  const limit = TIMEFRAMES.find((item) => item.value === timeframe)?.limit ?? 500;
  const request = useRef(0);

  useEffect(() => {
    const id = ++request.current;
    const query = new URLSearchParams({ underlying, interval: timeframe, limit: String(limit) });
    fetch(`/api/gex/bars?${query}`)
      .then(async (response) => {
        if (!response.ok) throw new Error(`Bars unavailable (${response.status})`);
        return (await response.json()) as Bar[];
      })
      .then((bars) => {
        if (id === request.current) setState({ bars, loading: false, error: null, key });
      })
      .catch((error: unknown) => {
        if (id === request.current)
          setState((previous) => ({
            ...previous,
            loading: false,
            error: error instanceof Error ? error.message : "Error",
          }));
      });
  }, [underlying, timeframe, limit, key, connection, minuteStart]);

  const [lastLive, setLastLive] = useState<Bar | null>(null);
  if (liveBar !== lastLive) {
    setLastLive(liveBar);
    if (liveBar && state.bars.length)
      setState((previous) => ({ ...previous, bars: applyLiveMinute(previous.bars, liveBar) }));
  }

  return { bars: state.bars, loading: state.loading, error: state.error };
}
