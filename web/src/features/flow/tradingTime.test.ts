import { expect, test } from "vitest";
import { closures, tradingTime } from "./tradingTime";

const ny = (iso: string) => Date.parse(iso) * 1e6; // ISO strings with an explicit offset
const HOUR = 3_600_000_000_000;

test("the daily close and the weekend are closed, across a clock change", () => {
  // Thu Nov 5 to Tue Nov 10, 2026 (US clocks went back on Sun Nov 1).
  const spans = closures(ny("2026-11-05T00:00:00-05:00"), ny("2026-11-10T23:00:00-05:00"));
  expect(spans).toEqual([
    [ny("2026-11-05T17:00:00-05:00"), ny("2026-11-05T18:00:00-05:00")],
    [ny("2026-11-06T17:00:00-05:00"), ny("2026-11-08T18:00:00-05:00")],
    [ny("2026-11-09T17:00:00-05:00"), ny("2026-11-09T18:00:00-05:00")],
    [ny("2026-11-10T17:00:00-05:00"), ny("2026-11-10T18:00:00-05:00")],
  ]);
  // A summer daily close is at 17:00 EDT.
  const summer = closures(ny("2026-07-14T12:00:00-04:00"), ny("2026-07-14T20:00:00-04:00"));
  expect(summer).toEqual([[ny("2026-07-14T17:00:00-04:00"), ny("2026-07-14T18:00:00-04:00")]]);
});

test("Friday's close sits right next to Sunday's open, and expand undoes compress", () => {
  const t = tradingTime(ny("2026-11-05T00:00:00-05:00"), ny("2026-11-12T00:00:00-05:00"));
  const friday = ny("2026-11-06T16:59:00-05:00");
  const sunday = ny("2026-11-08T18:01:00-05:00");
  expect(t.compress(sunday) - t.compress(friday)).toBe(2 * 60_000_000_000);
  // Thursday 4 PM to Thursday 7 PM is two trading hours.
  expect(t.compress(ny("2026-11-05T19:00:00-05:00")) - t.compress(ny("2026-11-05T16:00:00-05:00"))).toBe(
    2 * HOUR,
  );
  for (const ns of [friday, sunday, ny("2026-11-09T10:30:00-05:00"), ny("2026-11-11T18:00:00-05:00")])
    expect(t.expand(t.compress(ns))).toBe(ns);
  expect(t.closed(ny("2026-11-07T12:00:00-05:00"))).toBe(true);
  expect(t.closed(ny("2026-11-09T12:00:00-05:00"))).toBe(false);
});
