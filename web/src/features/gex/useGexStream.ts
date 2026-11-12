import { useEffect, useRef, useState } from "react";
import type { Bar, GexSnapshot, LiveUpdate } from "./types";

export type FeedStatus = "connecting" | "live" | "reconnecting" | "stale";

export type StreamOptions = {
  underlying: string;
  /** Nearest N expiries, or every tracked expiry when omitted. */
  expiries?: number | null;
  staleAfterMs?: number;
  maxBackoffMs?: number;
  createSocket?: (url: string) => WebSocket;
  now?: () => number;
};

export type StreamState = {
  snapshot: GexSnapshot | null;
  /** The forming 1-minute bar from the live stream. */
  liveBar: Bar | null;
  /** Increments on every (re)connect, so history can be reloaded. */
  connection: number;
  /** False during the daily CME halt and over the weekend. */
  marketOpen: boolean;
  status: FeedStatus;
  lastMessageAt: number | null;
  /** Client time when the snapshot's market time last moved forward. */
  lastAdvanceAt: number | null;
  noData: boolean;
};

const BASE_BACKOFF_MS = 500;
const INITIAL: StreamState = {
  snapshot: null,
  liveBar: null,
  connection: 0,
  marketOpen: true,
  status: "connecting",
  lastMessageAt: null,
  lastAdvanceAt: null,
  noData: false,
};

function socketUrl(path: string): string {
  const { protocol, host } = window.location;
  return `${protocol === "https:" ? "wss" : "ws"}://${host}${path}`;
}

/**
 * Live GEX snapshots and price bars for one underlying over a WebSocket. Reconnects
 * with capped, jittered backoff and reloads snapshot and bars after every
 * (re)connect. Out-of-order snapshots are ignored within a connection; a restarted
 * service may begin at an earlier market time, so each connection starts fresh.
 */
export function useGexStream({
  underlying,
  expiries = null,
  staleAfterMs = 5000,
  maxBackoffMs = 10_000,
  createSocket = (url) => new WebSocket(url),
  now = Date.now,
}: StreamOptions): StreamState {
  const key = `${underlying}|${expiries ?? "all"}`;
  const [state, setState] = useState<StreamState & { key: string }>({ ...INITIAL, key });
  if (state.key !== key) {
    // Switching symbol or expiries starts from a clean slate instead of showing stale data.
    setState({ ...INITIAL, key });
  }
  const options = useRef({ createSocket, now, staleAfterMs, maxBackoffMs });

  useEffect(() => {
    const { createSocket, now, staleAfterMs, maxBackoffMs } = options.current;
    const query = `underlying=${encodeURIComponent(underlying)}${expiries ? `&expiries=${expiries}` : ""}`;
    let socket: WebSocket | null = null;
    let attempt = 0;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    let newestAsOf = -Infinity;

    const accept = (update: LiveUpdate) => {
      const snapshot = update.snapshot;
      const outOfOrder = snapshot !== null && snapshot.as_of_ns < newestAsOf;
      const advanced = snapshot !== null && snapshot.as_of_ns > newestAsOf;
      if (snapshot && !outOfOrder) newestAsOf = snapshot.as_of_ns;
      setState((previous) => {
        const at = now();
        if (outOfOrder) return { ...previous, status: "live", lastMessageAt: at };
        return {
          ...previous,
          snapshot: snapshot ?? previous.snapshot,
          liveBar: update.bar ?? previous.liveBar,
          marketOpen: update.market_open ?? true,
          status: "live",
          lastMessageAt: at,
          lastAdvanceAt: advanced ? at : previous.lastAdvanceAt,
          noData: false,
        };
      });
    };

    async function loadLatest() {
      try {
        const latest = await fetch(`/api/gex/live/latest?${query}`);
        if (closed) return;
        if (latest.status === 503) {
          setState((previous) => ({ ...previous, noData: previous.snapshot === null }));
        } else if (latest.ok) {
          accept((await latest.json()) as LiveUpdate);
        }
      } catch {
        // The socket reports connection problems; this is a best-effort refresh.
      }
    }

    function connect() {
      if (closed) return;
      socket = createSocket(socketUrl(`/api/gex/ws/live?${query}`));
      socket.onopen = () => {
        attempt = 0;
        newestAsOf = -Infinity;
        setState((previous) => ({ ...previous, connection: previous.connection + 1 }));
        void loadLatest();
      };
      socket.onmessage = (event: MessageEvent) => {
        try {
          accept(JSON.parse(String(event.data)) as LiveUpdate);
        } catch {
          // Ignore a malformed frame rather than dropping the connection.
        }
      };
      socket.onclose = () => {
        if (closed) return;
        setState((previous) => ({ ...previous, status: "reconnecting" }));
        const delay = Math.min(maxBackoffMs, BASE_BACKOFF_MS * 2 ** attempt) * (0.5 + Math.random() / 2);
        attempt += 1;
        retryTimer = setTimeout(connect, delay);
      };
    }

    void loadLatest();
    connect();
    const staleTimer = setInterval(() => {
      setState((previous) =>
        previous.status === "live" &&
        previous.lastMessageAt !== null &&
        now() - previous.lastMessageAt > staleAfterMs
          ? { ...previous, status: "stale" }
          : previous,
      );
    }, 1000);

    return () => {
      closed = true;
      clearTimeout(retryTimer);
      clearInterval(staleTimer);
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    };
  }, [underlying, expiries]);

  return state;
}
