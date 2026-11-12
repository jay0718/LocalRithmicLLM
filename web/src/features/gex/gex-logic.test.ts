import { makeSnapshot } from "./fixtures";
import { formatGex, symmetricTicks } from "./format";
import { strikesAround, withConvention } from "./types";

test.each([
  [1.24e9, "$1.24B"],
  [-350e6, "-$350M"],
  [500e6, "$500M"], // regression: trailing zeros of whole numbers were stripped to "$5M"
  [1e9, "$1B"],
  [2.5e9, "$2.5B"],
  [12_000, "$12K"],
  [0, "$0"],
])("formatGex(%d) = %s", (value, expected) => {
  expect(formatGex(value)).toBe(expected);
});

test("ticks are symmetric, round and cover the data", () => {
  const { limit, ticks } = symmetricTicks(1.3e9);
  expect(limit).toBeGreaterThanOrEqual(1.3e9);
  expect(ticks).toContain(0);
  expect(ticks[0]).toBe(-limit);
  expect(ticks.at(-1)).toBe(limit);
  expect(symmetricTicks(0).ticks).toEqual([-1, 0, 1]);
});

test("flipping the dealer convention negates exposure but keeps levels", () => {
  const snapshot = makeSnapshot();
  const flipped = withConvention(snapshot, "short_calls_long_puts");
  expect(flipped.total_gex).toBe(-snapshot.total_gex);
  expect(flipped.strikes[0]?.net_gex).toBe(-(snapshot.strikes[0]?.net_gex ?? 0));
  expect([flipped.flip_level, flipped.call_wall, flipped.put_wall]).toEqual([
    snapshot.flip_level,
    snapshot.call_wall,
    snapshot.put_wall,
  ]);
  expect(withConvention(snapshot, snapshot.convention)).toBe(snapshot);
});

test("strikesAround centers on spot and sorts high to low", () => {
  const rows = strikesAround(makeSnapshot({ spot: 6001 }), 1);
  expect(rows.map((row) => row.strike)).toEqual([6025, 6000, 5975]);
  expect(strikesAround(makeSnapshot({ strikes: [] }), 5)).toEqual([]);
});
