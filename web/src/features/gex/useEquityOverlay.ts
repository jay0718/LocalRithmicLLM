import { useEffect, useState } from "react";
import type { components } from "../../api/gex";

export type EquityOverlay = components["schemas"]["EquityOverlay"];
export type OverlayState = { status: "off" | "building" | "ready" | "error"; overlay: EquityOverlay | null };

const REFRESH_MS = 10 * 60_000;
const RETRY_MS = 60_000;

/**
 * End-of-day GEX of the ETF paired with a future (QQQ for NQ), already rescaled to futures points.
 * The service builds it once per session, which can take half an hour, so it is polled slowly.
 */
export function useEquityOverlay(
  underlying: string,
  etf: string | null | undefined,
  expiries: number | null = null,
): OverlayState {
  const key = `${underlying}|${etf ?? ""}|${expiries ?? "all"}`;
  const [state, setState] = useState<OverlayState & { key: string }>({ key, status: "off", overlay: null });
  if (state.key !== key) setState({ key, status: "off", overlay: null });

  useEffect(() => {
    if (!etf) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      let ready = false;
      try {
        const query = `underlying=${encodeURIComponent(underlying)}${expiries ? `&expiries=${expiries}` : ""}`;
        const response = await fetch(`/api/gex/overlays/equity?${query}`);
        if (response.ok) {
          const overlay = (await response.json()) as EquityOverlay;
          ready = true;
          if (!cancelled) setState({ key, status: "ready", overlay });
        } else if (!cancelled) {
          setState((current) =>
            current.overlay
              ? current
              : { key, status: response.status === 503 ? "building" : "error", overlay: null },
          );
        }
      } catch {
        if (!cancelled)
          setState((current) => (current.overlay ? current : { key, status: "error", overlay: null }));
      }
      if (!cancelled) timer = setTimeout(() => void load(), ready ? REFRESH_MS : RETRY_MS);
    }
    void load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [underlying, etf, expiries, key]);

  return state;
}
