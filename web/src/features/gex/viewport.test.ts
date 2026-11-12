import { INITIAL_VIEW, MAX_SLOT, MIN_SLOT, distance, maxOffsetFor, zoomAround } from "./viewport";

const capacityAt = (slot: number) => Math.floor(900 / slot);

test("zooming keeps the bar under the cursor in place", () => {
  const view = { ...INITIAL_VIEW, slot: 10, offset: 20 };
  const fromRight = 300; // 30 bars left of the right edge, so the cursor is over bar 50 from the end
  const zoomed = zoomAround(view, 2, fromRight, 5000, capacityAt);
  expect(zoomed.slot).toBe(20);
  expect(zoomed.offset + fromRight / zoomed.slot).toBeCloseTo(view.offset + fromRight / view.slot);
});

test("zoom is clamped and never scrolls past the newest bar", () => {
  expect(zoomAround(INITIAL_VIEW, 100, 0, 5000, capacityAt).slot).toBe(MAX_SLOT);
  expect(zoomAround(INITIAL_VIEW, 0.001, 0, 5000, capacityAt).slot).toBe(MIN_SLOT);
  expect(zoomAround({ ...INITIAL_VIEW, offset: 0 }, 2, 0, 5000, capacityAt).offset).toBe(0);
  expect(zoomAround({ ...INITIAL_VIEW, offset: 0 }, 0.5, 0, 5000, capacityAt).offset).toBe(0);
});

test("history can be scrolled until a fifth of the screen still has bars", () => {
  expect(maxOffsetFor(5000, 100)).toBe(4980);
  expect(maxOffsetFor(50, 100)).toBe(40);
});

test("distance needs two pointers", () => {
  expect(
    distance([
      { x: 0, y: 0 },
      { x: 3, y: 4 },
    ]),
  ).toBe(5);
  expect(distance([{ x: 0, y: 0 }])).toBeNull();
});

import { breaksBefore } from "./breaks";

test("breaks mark time gaps and session opens", () => {
  const ny = (iso: string) => new Date(iso).getTime() * 1e6;
  const bar = (iso: string) => ({
    start_ns: ny(iso),
    open: 1,
    high: 1,
    low: 1,
    close: 1,
    volume: 1,
    trades: 1,
  });
  const bars = [
    bar("2026-11-11T12:50:00Z"), // 7:50 AM ET
    bar("2026-11-11T12:55:00Z"),
    bar("2026-11-11T20:10:00Z"), // 3:10 PM ET after a hole
    bar("2026-11-11T21:55:00Z"), // 4:55 PM ET
    bar("2026-11-11T23:00:00Z"), // 6:00 PM ET session open
  ];
  expect(breaksBefore(bars, "5m")).toEqual([
    { index: 2, session: false },
    { index: 3, session: false },
    { index: 4, session: true },
  ]);
  expect(breaksBefore(bars, "1d")).toEqual([]);
});
