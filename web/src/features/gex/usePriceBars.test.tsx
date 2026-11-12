import { act, renderHook, waitFor } from "@testing-library/react";
import { json } from "../../test-utils";
import type { Bar } from "./types";
import { applyLiveMinute, usePriceBars, type Timeframe } from "./usePriceBars";

const bar = (start_ns: number, close: number, extra: Partial<Bar> = {}): Bar => ({
  start_ns,
  open: close,
  high: close,
  low: close,
  close,
  volume: 1,
  trades: 1,
  ...extra,
});

test("live minute extends range and close of the latest bar only", () => {
  const bars = [bar(0, 1), bar(300, 5, { high: 6, low: 4, volume: 10 })];
  const updated = applyLiveMinute(bars, bar(360, 7, { high: 8, low: 3 }));
  expect(updated[1]).toMatchObject({ start_ns: 300, open: 5, high: 8, low: 3, close: 7, volume: 10 });
  expect(updated[0]).toBe(bars[0]);
  expect(applyLiveMinute(bars, bar(-60, 1))).toBe(bars);
  expect(applyLiveMinute([], bar(0, 1))).toEqual([]);
});

test("loads by symbol and timeframe, and reloads when a new minute starts", async () => {
  const requests: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    requests.push(url);
    return json([bar(0, url.includes("interval=5m") ? 5 : 1)]);
  });
  const hook = renderHook(
    ({ timeframe, live }: { timeframe: Timeframe; live: Bar | null }) =>
      usePriceBars("ESZ6", timeframe, live, 1),
    { initialProps: { timeframe: "1m" as Timeframe, live: null as Bar | null } },
  );
  await waitFor(() => expect(hook.result.current.bars[0]?.close).toBe(1));
  hook.rerender({ timeframe: "5m", live: null });
  await waitFor(() => expect(hook.result.current.bars[0]?.close).toBe(5));
  expect(requests.at(-1)).toContain("underlying=ESZ6");
  const count = requests.length;
  hook.rerender({ timeframe: "5m", live: bar(60, 9) });
  await waitFor(() => expect(requests.length).toBe(count + 1));
  act(() => hook.rerender({ timeframe: "5m", live: bar(60, 10) }));
  expect(requests.length).toBe(count + 1);
});

test("reports a failed load", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ detail: "x" }, 502));
  const hook = renderHook(() => usePriceBars("ESZ6", "1m", null, 1));
  await waitFor(() => expect(hook.result.current.error).toBe("Bars unavailable (502)"));
});
