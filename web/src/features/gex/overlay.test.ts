import { OVERLAY, makeSnapshot } from "./fixtures";
import { bucketOverlay, withOverlay } from "./overlay";

test("ETF strikes are summed into the chart's buckets and follow the dealer convention", () => {
  const buckets = bucketOverlay(OVERLAY, 25, false);
  expect(buckets.get(6000)?.net_gex).toBe(2e9);
  expect(buckets.get(5975)?.net_gex).toBe(-3e9);
  expect(bucketOverlay(OVERLAY, 25, true).get(6000)?.net_gex).toBe(-2e9);
});

test("overlay adds empty futures rows where only the ETF has gamma", () => {
  const profile = withOverlay(makeSnapshot(), bucketOverlay(OVERLAY, 25, false), false);
  const row = profile.strikes.find((item) => item.strike === 6100);
  expect(row?.net_gex).toBe(0);
  expect(profile.king_node).toBe(6025);
});

test("combined profile sums each row and recomputes the walls", () => {
  const profile = withOverlay(makeSnapshot(), bucketOverlay(OVERLAY, 25, false), true);
  expect(profile.strikes.find((item) => item.strike === 6000)?.net_gex).toBeCloseTo(2.1e9);
  expect(profile.king_node).toBe(5975);
  expect(profile.king_node_gex).toBeCloseTo(-3.5e9);
  expect(profile.put_wall).toBe(5975);
  expect(profile.call_wall).toBe(6000);
  expect(profile.total_gex).toBeCloseTo(makeSnapshot().total_gex - 1e9);
});
