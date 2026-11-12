import { useEffect, useState } from "react";
import type { components } from "../../api/gex";

export type Cpr = components["schemas"]["CentralPivotRange"];
const REFRESH_MS = 5 * 60_000;
const RETRY_MS = 10_000;

/** Prior-session CPR for a symbol. It changes once a day, so a slow refresh is enough. */
export function useCpr(underlying: string): Cpr | null {
  const [state, setState] = useState<{ underlying: string; cpr: Cpr | null }>({ underlying, cpr: null });
  if (state.underlying !== underlying) setState({ underlying, cpr: null });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      let loaded = false;
      try {
        const response = await fetch(`/api/gex/levels/cpr?underlying=${encodeURIComponent(underlying)}`);
        if (response.ok) {
          const cpr = (await response.json()) as Cpr;
          loaded = true;
          if (!cancelled) setState({ underlying, cpr });
        }
      } catch {
        // CPR is an optional overlay; keep the last value on a failed refresh.
      }
      // Retry soon until the first load succeeds, then refresh slowly.
      if (!cancelled) timer = setTimeout(() => void load(), loaded ? REFRESH_MS : RETRY_MS);
    }
    void load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [underlying]);

  return state.cpr;
}
