import { makeSnapshot } from "./fixtures";
import { bucketChoices, defaultBucket, groupStrikes, nativeStep } from "./types";

const strikes = [21400, 21425, 21450, 21475, 21500, 21525].map((strike, index) => ({
  strike,
  call_gex: index * 10,
  put_gex: -index,
  net_gex: index * 9,
}));
const snapshot = makeSnapshot({ strikes, spot: 21460, call_wall: 21525, put_wall: 21425, king_node: 21475 });

test("native step is the smallest strike gap", () => {
  expect(nativeStep(snapshot)).toBe(25);
});

test("choices start at the native step and stay round multiples", () => {
  expect(bucketChoices(25)).toEqual([25, 50, 100, 200, 250, 500, 1000]);
  expect(bucketChoices(5)).toEqual([5, 10, 25, 50, 100, 200]);
});

test("default bucket is about 0.4% of price", () => {
  expect(defaultBucket(25, 21500)).toBe(100);
  expect(defaultBucket(5, 6000)).toBe(25);
  expect(defaultBucket(5, 2400)).toBe(10);
});

test("grouping sums exposure into buckets and keeps the totals", () => {
  const grouped = groupStrikes(snapshot, 100);
  expect(grouped.strikes.map((row) => row.strike)).toEqual([21400, 21500]);
  const total = (rows: typeof strikes) => rows.reduce((sum, row) => sum + row.net_gex, 0);
  expect(total(grouped.strikes)).toBe(total(strikes));
  expect(grouped.strikes[0]).toEqual({ strike: 21400, call_gex: 10, put_gex: -1, net_gex: 9 });
});

test("levels move to the bucket that contains them", () => {
  const grouped = groupStrikes(snapshot, 100);
  expect([grouped.call_wall, grouped.put_wall, grouped.king_node]).toEqual([21500, 21400, 21500]);
});

test("grouping at or below the native step changes nothing", () => {
  expect(groupStrikes(snapshot, 25)).toBe(snapshot);
});
