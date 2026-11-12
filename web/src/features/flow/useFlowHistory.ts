import { useEffect, useState } from "react";
import type { components } from "../../api/gex";

export type FlowHistory = components["schemas"]["FlowHistoryOut"];
export type NodeFrame = components["schemas"]["NodeFrame"];
export type Bar = components["schemas"]["Bar"];

type Load<T> = { status: "loading" | "ready" | "error"; data: T | null };

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status}`);
  return (await response.json()) as T;
}

/** Sessions that have a replayed flow history for this future. */
export function useFlowDates(underlying: string): Load<string[]> {
  const [state, setState] = useState<Load<string[]> & { key: string }>({
    key: underlying,
    status: "loading",
    data: null,
  });
  if (state.key !== underlying) setState({ key: underlying, status: "loading", data: null });
  useEffect(() => {
    let cancelled = false;
    getJson<string[]>(`/api/gex/flow/dates?underlying=${encodeURIComponent(underlying)}`)
      .then((data) => !cancelled && setState({ key: underlying, status: "ready", data }))
      .catch(() => !cancelled && setState({ key: underlying, status: "error", data: null }));
    return () => {
      cancelled = true;
    };
  }, [underlying]);
  return state;
}

/**
 * Which trades the nodes leave out (see FlowRules on the server). Both filters are on by default;
 * each combination is computed separately, so switching one loads a different set of nodes.
 */
export type FlowFilters = { skipInside: boolean; skipLocked: boolean };
export const DEFAULT_FILTERS: FlowFilters = { skipInside: true, skipLocked: true };

/** Query parameters for filters that differ from the defaults ("" when both are on). */
export function filterQuery(filters: FlowFilters = DEFAULT_FILTERS): string {
  return (filters.skipInside ? "" : "&skip_inside=false") + (filters.skipLocked ? "" : "&skip_locked=false");
}

/** One session's node frames plus the future's minute bars over the same span. */
export function useFlowSession(
  underlying: string,
  date: string | null,
  filters: FlowFilters = DEFAULT_FILTERS,
): Load<{ history: FlowHistory; bars: Bar[] }> {
  const rules = filterQuery(filters);
  const key = `${underlying}|${date ?? ""}|${rules}`;
  const [state, setState] = useState<Load<{ history: FlowHistory; bars: Bar[] }> & { key: string }>({
    key,
    status: "loading",
    data: null,
  });
  if (state.key !== key) setState({ key, status: "loading", data: null });
  useEffect(() => {
    if (!date) return;
    let cancelled = false;
    (async () => {
      const history = await getJson<FlowHistory>(
        `/api/gex/flow/history?underlying=${encodeURIComponent(underlying)}&date=${date}${rules}`,
      );
      const first = history.overnight?.ts_ns ?? history.frames[0]?.ts_ns ?? 0;
      const last = history.frames.at(-1)?.ts_ns ?? 0;
      const minute = 60_000_000_000;
      const bars = await getJson<Bar[]>(
        `/api/gex/bars?underlying=${encodeURIComponent(underlying)}&interval=1m&limit=20000` +
          `&start_ns=${first - LOOKBACK_NS}&end_ns=${last + minute}`,
      );
      if (!cancelled) setState({ key, status: "ready", data: { history, bars } });
    })().catch(() => !cancelled && setState({ key, status: "error", data: null }));
    return () => {
      cancelled = true;
    };
  }, [underlying, date, key, rules]);
  return state;
}

/**
 * Future price per ETF dollar. The service sends the session's ratio (4pm future price / ETF spot);
 * without it, the first bar and first frame give an estimate.
 */
export function sessionRatio(history: FlowHistory, bars: Bar[]): number | null {
  if (history.ratio) return history.ratio;
  const frame = history.frames[0];
  const bar = bars.find((item) => frame && item.start_ns >= frame.ts_ns - 60_000_000_000);
  return frame && bar ? bar.close / frame.spot : null;
}

/** The frame's nodes, strongest first, limited to the top N. */
export function topNodes(frame: NodeFrame, count: number) {
  return [...frame.nodes].sort((a, b) => Math.abs(b.value) - Math.abs(a.value)).slice(0, count);
}

const timeFormat = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "America/New_York",
});

/** Clock time in New York, e.g. 12:12 PM. */
export function formatTime(ns: number): string {
  return timeFormat.format(new Date(ns / 1e6));
}

const dayFormat = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "America/New_York",
});

/** Calendar day in New York, e.g. Nov 9. */
export function formatDay(ns: number): string {
  return dayFormat.format(new Date(ns / 1e6));
}

const hourFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hour: "numeric",
  hourCycle: "h23",
});

/** The hour of day (0–23) in New York. */
export function nyHour(ns: number): number {
  return Number(hourFormat.format(new Date(ns / 1e6))) % 24;
}

/** A week of candles before the session is loaded too, so the chart can zoom out over it. */
export const LOOKBACK_NS = 7 * 24 * 60 * 60_000_000_000;
const DAY_NS = 24 * 60 * 60_000_000_000;

/** Fresh bars replace the tail of the loaded ones from their first minute on. */
export function mergeBars(loaded: Bar[], fresh: Bar[]): Bar[] {
  const from = fresh[0]?.start_ns;
  if (from === undefined) return loaded;
  return [...loaded.filter((bar) => bar.start_ns < from), ...fresh];
}

const MINUTE_NS = 60_000_000_000;
/** Streaming frames: one per 10 seconds of market time, matching the server. */
export const STREAM_STEP_NS = 10_000_000_000;
const BARS_REFRESH_MS = 15_000;
const RECONNECT_MS = 3_000;

const nyDay = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" });

/** YYYY-MM-DD in New York for a nanosecond timestamp. */
function nyDate(ns: number): string {
  return nyDay.format(new Date(ns / 1e6));
}

const nextPaint = (callback: () => void) =>
  typeof requestAnimationFrame === "function" ? requestAnimationFrame(callback) : setTimeout(callback, 16);

// A stable default, so the live effect does not reconnect on every render.
const openSocket = (url: string) => new WebSocket(url);

/** Whether the service is running live flow: 404 means it is not configured. */
export function useFlowLiveAvailable(underlying: string): boolean {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetch(`/api/gex/flow/live?underlying=${encodeURIComponent(underlying)}`)
      .then((response) => !cancelled && setAvailable(response.status !== 404))
      .catch(() => !cancelled && setAvailable(false));
    return () => {
      cancelled = true;
    };
  }, [underlying]);
  return available;
}

/** Adds a frame from the live stream: it replaces the frame for the same market minute. */
export function mergeFrame(frames: NodeFrame[], frame: NodeFrame, step = MINUTE_NS): NodeFrame[] {
  const last = frames.at(-1);
  if (last && Math.floor(last.ts_ns / step) === Math.floor(frame.ts_ns / step)) {
    return [...frames.slice(0, -1), frame];
  }
  if (last && frame.ts_ns < last.ts_ns) return frames;
  return [...frames, frame];
}

/**
 * Live flow: the session so far from /flow/live, then each new frame over /ws/flow, with the
 * future's minute bars refreshed every few seconds. Reconnects if the stream drops.
 */
export function useFlowLive(
  underlying: string,
  enabled: boolean,
  createSocket: (url: string) => WebSocket = openSocket,
  filters: FlowFilters = DEFAULT_FILTERS,
  streaming = false,
): Load<{ history: FlowHistory; bars: Bar[] }> {
  // Streaming: a frame per 10 seconds (kept by the server, so it survives reloads) instead of per minute.
  const rules = filterQuery(filters) + (streaming ? "&stream=true" : "");
  const step = streaming ? STREAM_STEP_NS : MINUTE_NS;
  const [state, setState] = useState<Load<{ history: FlowHistory; bars: Bar[] }>>({
    status: "loading",
    data: null,
  });
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let socket: WebSocket | null = null;
    let barsTimer: ReturnType<typeof setInterval> | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const query = `underlying=${encodeURIComponent(underlying)}`;

    // The first load reaches back a few days; refreshes fetch only the session and merge it in.
    async function loadBars(history: FlowHistory, lookback = 2 * MINUTE_NS) {
      const first = history.overnight?.ts_ns ?? history.frames[0]?.ts_ns ?? 0;
      const bars = await getJson<Bar[]>(
        `/api/gex/bars?${query}&interval=1m&limit=20000&start_ns=${first - lookback}`,
      );
      if (!cancelled)
        setState((current) =>
          current.data
            ? { ...current, data: { ...current.data, bars: mergeBars(current.data.bars, bars) } }
            : current,
        );
    }

    async function start() {
      try {
        const history = await getJson<FlowHistory>(`/api/gex/flow/live?${query}${rules}`);
        if (cancelled) return;
        // Switching filters swaps the nodes; the candles already loaded stay until they are refreshed.
        setState((current) => ({ status: "ready", data: { history, bars: current.data?.bars ?? [] } }));
        void loadBars(history, LOOKBACK_NS);
        barsTimer = setInterval(() => void loadBars(history), BARS_REFRESH_MS);
        const { protocol, host } = window.location;
        socket = createSocket(
          `${protocol === "https:" ? "wss" : "ws"}://${host}/api/gex/ws/flow?${query}${rules}`,
        );
        // Frames can arrive many times a second; apply them once per screen refresh.
        let queued: NodeFrame[] = [];
        let flushing = false;
        const flush = () => {
          flushing = false;
          const batch = queued;
          queued = [];
          if (cancelled || !batch.length) return;
          setState((current) => batch.reduce(applyFrame, current));
        };
        socket.onmessage = (event: MessageEvent) => {
          queued.push(JSON.parse(String(event.data)) as NodeFrame);
          if (!flushing) {
            flushing = true;
            nextPaint(flush);
          }
        };
        const applyFrame = (current: Load<{ history: FlowHistory; bars: Bar[] }>, frame: NodeFrame) => {
          if (!current.data) return current;
          const live = current.data.history;
          // Frames dated before the session are the frozen overnight board; the rest are minutes.
          const history =
            nyDate(frame.ts_ns) < live.session_date
              ? { ...live, overnight: frame }
              : { ...live, frames: mergeFrame(live.frames, frame, step) };
          return { ...current, data: { ...current.data, history } };
        };
        socket.onclose = () => {
          if (cancelled) return;
          clearInterval(barsTimer);
          retry = setTimeout(() => void start(), RECONNECT_MS);
        };
      } catch {
        if (cancelled) return;
        setState((current) => (current.data ? current : { status: "error", data: null }));
        retry = setTimeout(() => void start(), RECONNECT_MS);
      }
    }
    void start();
    return () => {
      cancelled = true;
      clearInterval(barsTimer);
      clearTimeout(retry);
      socket?.close();
    };
  }, [underlying, enabled, createSocket, rules, step]);
  return state;
}

/**
 * Saved sessions from the week before ``before`` (a YYYY-MM-DD session date, or today), with each
 * one's futures-per-ETF ratio, so the chart can draw their nodes over their own days.
 */
export function usePastSessions(
  underlying: string,
  dates: string[] | null,
  before: string | null,
  filters: FlowFilters = DEFAULT_FILTERS,
) {
  const rules = filterQuery(filters);
  const [sessions, setSessions] = useState<{ key: string; data: { frames: NodeFrame[]; ratio: number }[] }>({
    key: "",
    data: [],
  });
  const key = before && dates ? `${underlying}:${before}:${dates.join(",")}:${rules}` : "";
  useEffect(() => {
    if (!key || !before || !dates) return;
    let cancelled = false;
    const cutoff = Date.parse(`${before}T00:00:00Z`) * 1e6 - 7 * DAY_NS;
    const wanted = dates.filter((date) => date < before && Date.parse(`${date}T00:00:00Z`) * 1e6 >= cutoff);
    void Promise.all(
      wanted.map((date) =>
        getJson<FlowHistory>(
          `/api/gex/flow/history?underlying=${encodeURIComponent(underlying)}&date=${date}${rules}`,
        ).catch(() => null),
      ),
    ).then((histories) => {
      if (cancelled) return;
      const data = histories.flatMap((history) =>
        history?.ratio ? [{ frames: history.frames, ratio: history.ratio }] : [],
      );
      setSessions({ key, data });
    });
    return () => {
      cancelled = true;
    };
  }, [key, underlying, before, dates, rules]);
  return sessions.key === key ? sessions.data : EMPTY_PAST;
}

const EMPTY_PAST: { frames: NodeFrame[]; ratio: number }[] = [];
