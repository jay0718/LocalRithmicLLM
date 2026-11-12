import { makeFitScale, makePriceScale, niceTicks, spreadLabels } from "./scale";

const rows = [6050, 6025, 6000, 5975].map((strike) => ({ strike, call_gex: 0, put_gex: 0, net_gex: 0 }));

test("strike scale is linear in price, one row per strike step", () => {
  const scale = makePriceScale(rows);
  expect(scale?.step).toBe(25);
  expect((scale?.y(6000) ?? 0) - (scale?.y(6025) ?? 0)).toBe(18);
  expect((scale?.y(6012.5) ?? 0) - (scale?.y(6025) ?? 0)).toBe(9);
  expect(scale?.contains(6060)).toBe(true);
  expect(scale?.contains(6100)).toBe(false);
});

test("strike scale stays linear when a strike is missing", () => {
  const gappy = rows.filter((row) => row.strike !== 6000);
  const scale = makePriceScale(gappy);
  expect((scale?.y(5975) ?? 0) - (scale?.y(6025) ?? 0)).toBe(36);
});

test("fit scale covers the candles with padding and a minimum span", () => {
  const scale = makeFitScale([100], [101], 400, 10);
  expect(scale?.contains(95.5)).toBe(true);
  expect((scale?.top ?? 0) - (scale?.bottom ?? 0)).toBeGreaterThanOrEqual(10);
  expect(makeFitScale([], [], 400, 10)).toBeNull();
});

test("nice ticks are round", () => {
  expect(niceTicks(5912, 6037)).toEqual([5925, 5950, 5975, 6000, 6025]);
});

test("labels are spread apart without reordering", () => {
  expect(spreadLabels([100, 105, 300])).toEqual([100, 113, 300]);
  expect(spreadLabels([105, 100])).toEqual([113, 100]);
});
