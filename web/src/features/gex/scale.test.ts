import { makePriceScale } from "./scale";
import type { StrikeGex } from "./types";

test("price scale shrinks rows to fit a maximum height, but not below the minimum", () => {
  const rows = Array.from({ length: 81 }, (_, index) => ({ strike: 7000 + index * 5 }) as StrikeGex);
  const roomy = makePriceScale(rows);
  expect(roomy?.row).toBe(18);
  const fitted = makePriceScale(rows, 700);
  expect(fitted?.height).toBeCloseTo(700);
  expect(fitted?.y(7400) ?? 0).toBeLessThan(fitted?.y(7000) ?? 0);
  expect(makePriceScale(rows, 200)?.row).toBe(7);
});
