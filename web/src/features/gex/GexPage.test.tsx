import { render as rtlRender, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { json, mockFetch } from "../../test-utils";
import userEvent from "@testing-library/user-event";
import { OVERLAY, makeSnapshot } from "./fixtures";
import { GexPage } from "./GexPage";
import * as stream from "./useGexStream";

const UNDERLYINGS = [
  {
    symbol: "ESZ6",
    product: "ES",
    name: "E-mini S&P 500",
    expiries: ["20261112", "20261113", "20261116", "20261117"],
  },
  { symbol: "NQZ6", product: "NQ", name: "E-mini Nasdaq-100" },
];

const BARS = [
  {
    start_ns: 1_794_000_000_000_000_000,
    open: 6000,
    high: 6004,
    low: 5998,
    close: 6002,
    volume: 30,
    trades: 9,
  },
  {
    start_ns: 1_794_000_060_000_000_000,
    open: 6002,
    high: 6006,
    low: 6001,
    close: 6005,
    volume: 20,
    trades: 7,
  },
];
const CPR = {
  session_date: "2026-11-06",
  high: 6050,
  low: 5950,
  close: 6020,
  pivot: 6006.67,
  bc: 6000,
  tc: 6013.33,
  r1: 6063.33,
  s1: 5963.33,
  r2: 6106.67,
  s2: 5906.67,
  width_pct: 0.22,
};

function render(ui: ReactElement, path = "/gex", extra: Parameters<typeof mockFetch>[0] = {}) {
  mockFetch({
    "GET /api/gex/underlyings": () => json(UNDERLYINGS),
    "GET /api/gex/bars": () => json(BARS),
    "GET /api/gex/levels/cpr": () => json(CPR),
    ...extra,
  });
  return rtlRender(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);
}

function mockStream(overrides: Partial<stream.StreamState> = {}) {
  vi.spyOn(stream, "useGexStream").mockReturnValue({
    snapshot: makeSnapshot(),
    liveBar: null,
    connection: 1,
    marketOpen: true,
    status: "live",
    lastMessageAt: Date.now(),
    lastAdvanceAt: Date.now(),
    noData: false,
    ...overrides,
  });
}

test("shows headline levels, scope and the synthetic label", async () => {
  mockStream();
  render(<GexPage />);
  const spotTile = screen.getByText("ESZ6 spot").closest(".stat") as HTMLElement;
  expect(within(spotTile).getByText("6,006.25")).toBeInTheDocument();
  expect(screen.getByText("$1B")).toBeInTheDocument();
  expect(screen.getByText("Synthetic data")).toBeInTheDocument();
  expect(screen.getByText(/dealer gamma per 1% move/)).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Live");
  expect(screen.getByRole("img", { name: /Net GEX for 5 rows/ })).toBeInTheDocument();
  expect(await screen.findByRole("img", { name: /ESZ6 1m price chart with 2 candles/ })).toBeInTheDocument();
  expect(screen.getByText("King node")).toBeInTheDocument();
});

test("dealer convention flips the headline sign and stays visible", async () => {
  mockStream();
  render(<GexPage />);
  await userEvent.selectOptions(
    screen.getByLabelText("Dealer positioning assumption"),
    "short_calls_long_puts",
  );
  expect(screen.getByText("-$1B")).toBeInTheDocument();
  expect(screen.getAllByText("Dealers short calls, long puts").length).toBeGreaterThan(0);
});

test("table view lists every shown strike", async () => {
  mockStream();
  render(<GexPage />);
  await userEvent.click(screen.getByRole("button", { name: "Table" }));
  const table = screen.getByRole("table", { name: "GEX by strike" });
  expect(within(table).getAllByRole("row")).toHaveLength(6);
  expect(within(table).getByText("6,025")).toBeInTheDocument();
});

test("strike range choice is remembered", async () => {
  mockStream();
  render(<GexPage />);
  await userEvent.selectOptions(screen.getByLabelText("Rows shown"), "10");
  expect(localStorage.getItem("lrl.gex.range")).toBe("10");
});

test.each([
  ["reconnecting", /Connection lost/],
  ["stale", /No updates for over 5 seconds/],
] as const)("%s feed greys out the chart with an explanation", (status, message) => {
  mockStream({ status });
  const { container } = render(<GexPage />);
  expect(screen.getByRole("alert")).toHaveTextContent(message);
  expect(container.querySelector(".gex-plot")).toHaveClass("is-stale");
});

test("warns when market time stops advancing", () => {
  mockStream({ lastAdvanceAt: Date.now() - 120_000 });
  render(<GexPage />);
  expect(screen.getByText(/Market time hasn't moved for over a minute/)).toBeInTheDocument();
});

test("no data and connecting states never show an empty chart", () => {
  mockStream({ snapshot: null, status: "connecting", noData: true });
  const { unmount } = render(<GexPage />);
  expect(screen.getByRole("heading", { name: "Waiting for market data" })).toBeInTheDocument();
  unmount();
  mockStream({ snapshot: null, status: "connecting", noData: false });
  render(<GexPage />);
  expect(screen.getByRole("heading", { name: "Connecting to the GEX service" })).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});

test("symbol picker lists underlyings and streams the chosen one", async () => {
  const spy = vi.spyOn(stream, "useGexStream").mockReturnValue({
    snapshot: makeSnapshot(),
    liveBar: null,
    connection: 1,
    marketOpen: true,
    status: "live",
    lastMessageAt: Date.now(),
    lastAdvanceAt: Date.now(),
    noData: false,
  });
  render(<GexPage />);
  const picker = screen.getByLabelText("Symbol");
  expect(await within(picker).findByRole("option", { name: "NQ · NQZ6" })).toBeInTheDocument();
  await userEvent.selectOptions(picker, "NQZ6");
  expect(spy).toHaveBeenLastCalledWith({ underlying: "NQZ6", expiries: null });
  expect(localStorage.getItem("lrl.gex.symbol")).toBe("NQZ6");
});

test("symbol comes from the URL", () => {
  const spy = vi.spyOn(stream, "useGexStream").mockReturnValue({
    snapshot: null,
    liveBar: null,
    connection: 0,
    marketOpen: true,
    status: "connecting",
    lastMessageAt: null,
    lastAdvanceAt: null,
    noData: false,
  });
  render(<GexPage />, "/gex?symbol=NQZ6");
  expect(spy).toHaveBeenLastCalledWith({ underlying: "NQZ6", expiries: null });
});

test("price scale toggle is remembered", async () => {
  mockStream({});
  render(<GexPage />);
  await userEvent.click(screen.getByRole("button", { name: "Match strikes" }));
  expect(screen.getByRole("button", { name: "Match strikes" })).toHaveAttribute("aria-pressed", "true");
  expect(localStorage.getItem("lrl.gex.priceScale")).toBe("strikes");
});

test("timeframe choice reloads bars and is remembered", async () => {
  mockStream();
  render(<GexPage />);
  await userEvent.click(screen.getByRole("button", { name: "1h" }));
  expect(localStorage.getItem("lrl.gex.timeframe")).toBe("1h");
  expect(await screen.findByRole("img", { name: /ESZ6 1h price chart/ })).toBeInTheDocument();
});

test("CPR overlay shows its session and levels", async () => {
  mockStream();
  render(<GexPage />);
  await userEvent.selectOptions(screen.getByLabelText("Central pivot range"), "pivots");
  expect(await screen.findByText(/CPR from the 2026-11-06 session/)).toBeInTheDocument();
  expect(localStorage.getItem("lrl.gex.cpr")).toBe("pivots");
  expect(screen.getAllByText(/Pivot 6,006.67/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/R2 6,106.67/).length).toBeGreaterThan(0);
});

test("strike grouping is offered from the native step and remembered per symbol", async () => {
  mockStream();
  render(<GexPage />);
  const group = screen.getByLabelText("Group strikes");
  expect(within(group).getByRole("option", { name: "Every strike (25)" })).toBeInTheDocument();
  await userEvent.selectOptions(group, "50");
  expect(localStorage.getItem("lrl.gex.bucket.ESZ6")).toBe("50");
  expect(screen.getByRole("heading", { name: "GEX per 50 points" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Net GEX for 3 rows/ })).toBeInTheDocument();
});

test("market closed shows the settlement basis", () => {
  mockStream({
    marketOpen: false,
    snapshot: makeSnapshot({
      data_source: "rithmic",
      priced_from_settlement: 28,
      oldest_settlement: "20261026",
    }),
  });
  render(<GexPage />);
  expect(screen.getByText(/Market closed/)).toHaveTextContent(
    "28 options priced from settlement, the oldest from 2026-10-26",
  );
  expect(screen.getByText("Rithmic")).toBeInTheDocument();
  expect(screen.queryByText("Synthetic data")).not.toBeInTheDocument();
});

test("node values show compact amounts and can be hidden", async () => {
  mockStream();
  render(<GexPage />);
  const chart = screen.getByRole("img", { name: /Net GEX for/ });
  // Fixture nodes are -$800M, -$500M, $100M, $1.1B and $400M.
  for (const text of ["-$800M", "$1.1B", "$400M"]) expect(within(chart).getByText(text)).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("Values"));
  expect(within(chart).queryByText("$1.1B")).not.toBeInTheDocument();
  expect(localStorage.getItem("lrl.gex.values")).toBe("off");
});

test("expiry selector lists upcoming expiries and streams the chosen count", async () => {
  const spy = vi.spyOn(stream, "useGexStream").mockReturnValue({
    snapshot: makeSnapshot(),
    liveBar: null,
    connection: 1,
    marketOpen: true,
    status: "live",
    lastMessageAt: Date.now(),
    lastAdvanceAt: Date.now(),
    noData: false,
  });
  render(<GexPage />);
  const picker = await screen.findByLabelText("Expiries");
  expect(
    within(picker)
      .getAllByRole("option")
      .map((o) => o.textContent),
  ).toEqual([
    "Next expiry: Nov 12",
    "Next 2 (to Nov 13)",
    "Next 3 (to Nov 16)",
    "All 4 expiries (to Nov 17)",
  ]);
  await userEvent.selectOptions(picker, "1");
  expect(spy).toHaveBeenLastCalledWith({ underlying: "ESZ6", expiries: 1 });
  expect(localStorage.getItem("lrl.gex.expiries")).toBe("1");
  await userEvent.selectOptions(picker, "0");
  expect(spy).toHaveBeenLastCalledWith({ underlying: "ESZ6", expiries: null });
  expect(screen.getByText("Nov 12, Nov 13")).toBeInTheDocument();
});

test("ETF overlay draws outlined bars, and combined mode recomputes the headline levels", async () => {
  mockStream();
  const withSpy = [{ ...UNDERLYINGS[0], overlay: "SPY" }, UNDERLYINGS[1]];
  render(<GexPage />, "/gex", {
    "GET /api/gex/underlyings": () => json(withSpy),
    "GET /api/gex/overlays/equity": () => json(OVERLAY),
  });
  expect(
    await screen.findByText(/SPY options expiring Nov 12, Nov 13, from the Nov 11 close: \$600\.60 × 10\.00/),
  ).toBeInTheDocument();
  expect(screen.getByText(/SPY \(end of day\)/)).toBeInTheDocument();
  const chart = screen.getByRole("img", { name: /Net GEX for/ });
  expect(chart.querySelectorAll(".bar-overlay").length).toBeGreaterThan(0);
  expect(statValue("King node")).toBe("6,025");

  await userEvent.selectOptions(screen.getByLabelText("SPY overlay"), "combined");
  expect(chart.querySelectorAll(".bar-overlay")).toHaveLength(0);
  expect(statValue("King node")).toBe("5,975");
  expect(statValue("Put wall")).toBe("5,975");
  expect(screen.getByText("Net GEX (ESZ6 + SPY)")).toBeInTheDocument();
  expect(localStorage.getItem("lrl.gex.overlay")).toBe("combined");
});

function statValue(label: string): string | null | undefined {
  return screen.getByText(label).closest(".stat")?.querySelector(".stat-value")?.textContent;
}
