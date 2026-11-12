import { useEffect, useState } from "react";
import type { Bar } from "./useFlowHistory";

/** The forming bar and the one that finished before it, from /ws/bars. */
export type BarTick = { bar: Bar; previous: Bar | null };

const RECONNECT_MS = 3_000;

const nextPaint = (callback: () => void) =>
  typeof requestAnimationFrame === "function" ? requestAnimationFrame(callback) : setTimeout(callback, 16);

function openSocket(url: string): WebSocket {
  return new WebSocket(url);
}

/**
 * The live futures bar, sent by the server as soon as a trade changes it (not once per GEX
 * computation), applied at most once per screen refresh. When a minute closes, the message that
 * opens the next one carries the finished bar's final shape.
 */
export function useLiveBar(
  underlying: string,
  enabled: boolean,
  createSocket: (url: string) => WebSocket = openSocket,
): BarTick | null {
  const [tick, setTick] = useState<BarTick | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let latest: BarTick | null = null;
    let queued = false;
    function connect() {
      const { protocol, host } = window.location;
      socket = createSocket(
        `${protocol === "https:" ? "wss" : "ws"}://${host}/api/gex/ws/bars?underlying=${encodeURIComponent(underlying)}`,
      );
      socket.onmessage = (event: MessageEvent) => {
        latest = JSON.parse(String(event.data)) as BarTick;
        if (queued) return;
        queued = true;
        nextPaint(() => {
          queued = false;
          if (!cancelled && latest) setTick(latest);
        });
      };
      socket.onclose = () => {
        if (!cancelled) retry = setTimeout(connect, RECONNECT_MS);
      };
    }
    connect();
    return () => {
      cancelled = true;
      clearTimeout(retry);
      socket?.close();
    };
  }, [underlying, enabled, createSocket]);
  return enabled ? tick : null;
}

/** Loaded bars with the live tick merged in: the finished bar replaces its minute, the forming one is added. */
export function withLiveBar(bars: Bar[], tick: BarTick | null): Bar[] {
  if (!tick) return bars;
  let merged = bars;
  for (const bar of [tick.previous, tick.bar]) {
    if (!bar) continue;
    const last = merged.at(-1);
    if (last && bar.start_ns < last.start_ns) {
      // An older minute: replace it in place if it is loaded.
      const index = merged.findIndex((item) => item.start_ns === bar.start_ns);
      if (index >= 0) merged = [...merged.slice(0, index), bar, ...merged.slice(index + 1)];
    } else if (last && last.start_ns === bar.start_ns) merged = [...merged.slice(0, -1), bar];
    else merged = [...merged, bar];
  }
  return merged;
}
