import { expect, test } from "vitest";
import {
  distanceTo,
  measure,
  moved,
  nextLevel,
  pick,
  rayEnd,
  type Drawing,
  type Projection,
} from "./drawings";

// One pixel per nanosecond-unit and per price point keeps the geometry readable.
const p: Projection = { x: (ns) => ns, y: (price) => 100 - price, right: 200 };

test("a trend line is picked near its segment, not past its end", () => {
  const line: Drawing = { id: "t", kind: "trend", a: { ns: 0, price: 0 }, b: { ns: 100, price: 100 } };
  expect(distanceTo(line, 50, 50, p)).toBeCloseTo(0);
  expect(distanceTo(line, 150, -50, p)).toBeGreaterThan(50);
});

test("a ray runs on to the edge of the plot", () => {
  expect(rayEnd(0, 100, 10, 90, 200)).toEqual([200, -100]);
  const ray: Drawing = { id: "r", kind: "ray", a: { ns: 0, price: 0 }, b: { ns: 10, price: 10 } };
  expect(distanceTo(ray, 150, -50, p)).toBeCloseTo(0);
});

test("boxes are picked inside, and the closest drawing within reach wins", () => {
  const box: Drawing = { id: "b", kind: "rect", a: { ns: 10, price: 80 }, b: { ns: 60, price: 40 } };
  const level: Drawing = { id: "h", kind: "hline", price: 50 };
  expect(pick([box, level], 30, 30, p)?.id).toBe("b");
  expect(pick([box, level], 100, 51, p)?.id).toBe("h");
  expect(pick([box, level], 100, 90, p)).toBeNull();
});

test("moving shifts both points; measuring gives change, percent and minutes", () => {
  const line: Drawing = { id: "t", kind: "trend", a: { ns: 0, price: 100 }, b: { ns: 60e9, price: 110 } };
  const shifted = moved(line, 60e9, -5);
  expect(shifted.kind === "trend" && [shifted.a, shifted.b]).toEqual([
    { ns: 60e9, price: 95 },
    { ns: 120e9, price: 105 },
  ]);
  expect(measure({ ns: 0, price: 100 }, { ns: 300e9, price: 110 })).toEqual({
    change: 10,
    percent: 10,
    minutes: 5,
  });
});

test("a Fibonacci drawing is picked across its extension levels too", () => {
  const fib: Drawing = {
    id: "f",
    kind: "fib",
    a: { ns: 10, price: 60 },
    b: { ns: 60, price: 50 },
    fib: { levels: [{ value: 2.618, color: "#000", visible: true }], fill: false },
  };
  // 2.618 sits at price 50 + 10 × 2.618 ≈ 76.2, i.e. y ≈ 23.8, far above the two points.
  expect(distanceTo(fib, 30, 25, p)).toBe(0);
  expect(nextLevel({ levels: [{ value: 0.886, color: "#000", visible: true }], fill: false }).value).toBe(
    1.272,
  );
});

test("one-minute bars combine into clock-aligned candles only for a longer interval", async () => {
  const { combine } = await import("./bars");
  const minute = 60_000_000_000;
  const bars = [0, 1, 2, 3, 4, 5].map((i) => ({
    start_ns: (100 + i) * minute,
    open: 10 + i,
    high: 20 + i,
    low: 5 - i,
    close: 11 + i,
    volume: 1,
    trades: 1,
  }));
  expect(combine(bars, 1)).toBe(bars);
  const five = combine(bars, 5);
  expect(five.map((bar) => bar.start_ns / minute)).toEqual([100, 105]);
  expect(five[0]).toMatchObject({ open: 10, high: 24, low: 1, close: 15, volume: 5 });
});

test("the hovered minute's frame is found by time, so missing minutes never shift it", async () => {
  const { frameAt } = await import("./bars");
  const minute = 60_000_000_000;
  // Frames for 10:55, 10:58 and 11:06 only (gaps in between).
  const frames = [55, 58, 66].map((m) => ({ ts_ns: m * minute + 30_000_000_000 }));
  // Pointing at 10:59 gives 10:58's frame, never 11:06's (which index counting would give).
  expect(frameAt(frames, 59 * minute + minute - 1)).toBe(1);
  expect(frameAt(frames, 54 * minute)).toBe(-1);
  expect(frameAt(frames, 70 * minute)).toBe(2);
});
