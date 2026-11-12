import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { json, mockFetch } from "../../test-utils";
import { FlowPage } from "./FlowPage";
import { tradingTime } from "./tradingTime";

const MINUTE = 60_000_000_000;
// 2026-11-10 9:31 AM ET
const OPEN = 1_794_324_660_000_000_000;

const HISTORY = {
  symbol: "QQQ",
  expiry: "20261110",
  session_date: "2026-11-10",
  ratio: 41.25,
  overnight_ratio: 41.27,
  // The previous session's close, Nov 9 4:15 PM ET.
  overnight: { ts_ns: OPEN - (17 * 60 + 16) * MINUTE, spot: 678.9, nodes: [{ strike: 686, value: 7.9e6 }] },
  frames: [
    {
      ts_ns: OPEN,
      spot: 675,
      nodes: [
        { strike: 680, value: 2e6 },
        { strike: 674, value: -1e6 },
      ],
    },
    {
      ts_ns: OPEN + MINUTE,
      spot: 674,
      call_wall: 680,
      put_wall: 674,
      flip: 677.5,
      total: -12e6,
      nodes: [
        { strike: 674, value: -8e6 },
        { strike: 671, value: -6e6 },
        { strike: 680, value: 2e6 },
      ],
    },
  ],
};

const BARS = [0, 1].map((index) => ({
  start_ns: OPEN - MINUTE + index * MINUTE,
  open: 27_800,
  high: 27_810,
  low: 27_790,
  close: 27_805,
  volume: 10,
  trades: 5,
}));

// Each test starts with no remembered view choices or drawings.
beforeEach(() => localStorage.clear());

function renderPage(dates: string[] = ["2026-11-10"]) {
  const calls = mockFetch({
    "GET /api/gex/flow/dates": () => json(dates),
    "GET /api/gex/flow/history": () => json(HISTORY),
    "GET /api/gex/bars": () => json(BARS),
  });
  render(
    <MemoryRouter>
      <FlowPage />
    </MemoryRouter>,
  );
  return calls;
}

test("shows the latest session's last minute, strongest node first", async () => {
  const calls = renderPage();
  const table = await screen.findByRole("table", { name: /flow nodes/ });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows.map((row) => within(row).getAllByRole("cell")[1]?.textContent)).toEqual(["674", "671", "680"]);
  expect(within(rows[0] as HTMLElement).getByText("★")).toBeInTheDocument();
  expect(within(rows[0] as HTMLElement).getByText("27,802.50")).toBeInTheDocument();
  expect(within(rows[1] as HTMLElement).getByText("75.0%")).toBeInTheDocument();
  expect(screen.getByText(/QQQ × 41.250 = NQ/)).toBeInTheDocument();
  const barsCall = calls.find((call) => call.url.includes("/bars"));
  // Bars reach a week before the overnight board, so the chart can zoom out over it.
  expect(barsCall?.url).toContain(`start_ns=${HISTORY.overnight.ts_ns - 7 * 24 * 60 * MINUTE}`);
});

test("hovering before the open shows the overnight board from the previous close", async () => {
  renderPage();
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  fireEvent.pointerMove(document.querySelector(".flow-scroll") as HTMLElement, { clientX: -1000 });
  expect(await screen.findByText("Overnight board, from the Nov 9 close")).toBeInTheDocument();
  const rows = within(screen.getByRole("table", { name: /flow nodes/ }))
    .getAllByRole("row")
    .slice(1);
  expect(rows).toHaveLength(1);
  // Mapped with the previous close's ratio.
  expect(within(rows[0] as HTMLElement).getByText("28,311.22")).toBeInTheDocument();
});

test("in session-only view, hovering the left edge selects the first minute", async () => {
  renderPage();
  await userEvent.selectOptions(await screen.findByLabelText("Chart window"), "session");
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  fireEvent.pointerMove(document.querySelector(".flow-scroll") as HTMLElement, { clientX: 9 });
  const table = await screen.findByRole("table", { name: /flow nodes/ });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows.map((row) => within(row).getAllByRole("cell")[1]?.textContent)).toEqual(["680", "674"]);
});

test("explains how to build a session when there are none", async () => {
  renderPage([]);
  expect(await screen.findByText(/No flow sessions yet/)).toBeInTheDocument();
});

test("wheel zooms the plot wider, double-click fits it again", async () => {
  renderPage();
  const chart = await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  const start = Number(chart.getAttribute("width"));
  const scroller = document.querySelector(".flow-scroll") as HTMLElement;
  fireEvent.wheel(scroller, { deltaY: -600, clientX: 100 });
  const zoomed = Number(screen.getByRole("img", { name: /flow nodes for 2 minutes/ }).getAttribute("width"));
  expect(zoomed).toBeGreaterThan(start * 1.5);
  fireEvent.doubleClick(scroller);
  const fitted = Number(screen.getByRole("img", { name: /flow nodes for 2 minutes/ }).getAttribute("width"));
  expect(fitted).toBeLessThan(start);
  expect(document.querySelector(".flow-axis")).not.toBeNull();
});

test("dragging scrolls without changing the selected minute", async () => {
  renderPage();
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  const scroller = document.querySelector(".flow-scroll") as HTMLElement;
  const title = () => document.querySelector(".flow-side .panel-title")?.textContent;
  const before = title();
  fireEvent.pointerDown(scroller, { clientX: 400, pointerId: 1 });
  fireEvent.pointerMove(scroller, { clientX: 200, pointerId: 1 });
  fireEvent.pointerUp(scroller, { clientX: 200, pointerId: 1 });
  expect(title()).toBe(before);
});

test("lists the selected minute's walls, flip and net gamma, and can hide the lines", async () => {
  renderPage();
  expect(await screen.findByText("680 · 28,050.00")).toBeInTheDocument();
  expect(screen.getByText("674 · 27,802.50")).toBeInTheDocument();
  expect(screen.getByText("677.50 · 27,946.88")).toBeInTheDocument();
  expect(screen.getByText("-$12M per $1 QQQ")).toBeInTheDocument();
  // The lines are off until turned on.
  expect(document.querySelectorAll(".flow-levels path")).toHaveLength(0);
  await userEvent.click(screen.getByLabelText("Walls"));
  expect(document.querySelector(".flow-level-call")).not.toBeNull();
  expect(document.querySelector(".flow-level-put")).not.toBeNull();
  expect(document.querySelector(".flow-level-flip")).toBeNull();
  await userEvent.click(screen.getByLabelText("Flip"));
  expect(document.querySelectorAll(".flow-levels path")).toHaveLength(3);
  await userEvent.click(screen.getByLabelText("Walls"));
  expect(document.querySelectorAll(".flow-levels path")).toHaveLength(1);
});

test("view choices are remembered after a reload", async () => {
  renderPage();
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  await userEvent.click(screen.getByLabelText("Walls"));
  await userEvent.selectOptions(screen.getByLabelText("Nodes shown"), "20");
  await userEvent.selectOptions(screen.getByLabelText("Chart window"), "session");
  await userEvent.selectOptions(screen.getByLabelText("Candle interval"), "5");
  cleanup();
  renderPage();
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  expect(screen.getByLabelText("Walls")).toBeChecked();
  expect(screen.getByLabelText("Flip")).not.toBeChecked();
  expect(screen.getByLabelText("Nodes shown")).toHaveValue("20");
  expect(screen.getByLabelText("Chart window")).toHaveValue("session");
  expect(screen.getByLabelText("Candle interval")).toHaveValue("5");
  expect(document.querySelector(".chart-legend")?.textContent).toMatch(/NQZ6 · 5m/);
});

test("no nodes option clears the dots but keeps the levels and the table", async () => {
  renderPage();
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  expect(document.querySelectorAll(".flow-dots circle").length).toBeGreaterThan(0);
  await userEvent.click(screen.getByLabelText("Walls"));
  await userEvent.click(screen.getByLabelText("Flip"));
  await userEvent.selectOptions(screen.getByLabelText("Nodes shown"), "0");
  expect(document.querySelectorAll(".flow-dots circle")).toHaveLength(0);
  expect(document.querySelectorAll(".flow-levels path")).toHaveLength(3);
  expect(
    within(screen.getByRole("table", { name: /flow nodes/ })).getAllByRole("row").length,
  ).toBeGreaterThan(1);
});

test("dragging up or down pans prices, the price axis stretches them, double-click resets", async () => {
  renderPage();
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  const ticks = () =>
    [...document.querySelectorAll(".flow-axis .axis-tick")].map((t) => t.textContent).join(",");
  const fitted = ticks();
  const scroller = document.querySelector(".flow-scroll") as HTMLElement;
  fireEvent.pointerDown(scroller, { clientX: 300, clientY: 200, pointerId: 1 });
  fireEvent.pointerMove(scroller, { clientX: 300, clientY: 320, pointerId: 1 });
  fireEvent.pointerUp(scroller, { clientX: 300, clientY: 320, pointerId: 1 });
  const panned = ticks();
  expect(panned).not.toBe(fitted);
  const axis = document.querySelector(".flow-axis") as SVGElement;
  fireEvent.pointerDown(axis, { clientY: 200, pointerId: 2 });
  fireEvent.pointerMove(axis, { clientY: 300, pointerId: 2 });
  fireEvent.pointerUp(axis, { clientY: 300, pointerId: 2 });
  expect(ticks()).not.toBe(panned);
  fireEvent.doubleClick(scroller);
  // With the pointer off the chart, no crosshair badge hides a tick.
  fireEvent.pointerLeave(scroller);
  expect(ticks()).toBe(fitted);
});

test("draw a horizontal line, select it, move it, delete it; drawings are kept per symbol", async () => {
  localStorage.clear();
  renderPage();
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  const scroller = document.querySelector(".flow-scroll") as HTMLElement;
  const levels = () =>
    [...document.querySelectorAll(".drawings line.drawing")].map((l) => l.getAttribute("y1"));

  fireEvent.click(screen.getByRole("button", { name: "Horizontal line" }));
  expect(screen.getByRole("button", { name: "Horizontal line" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.pointerDown(scroller, { clientX: 300, clientY: 200, pointerId: 1 });
  fireEvent.pointerUp(scroller, { clientX: 300, clientY: 200, pointerId: 1 });
  // One line at the click, the tool goes back to the cursor, and the price shows on the axis.
  expect(levels().map((v) => Math.round(Number(v)))).toEqual([200]);
  expect(screen.getByRole("button", { name: "Cursor" })).toHaveAttribute("aria-pressed", "true");
  expect(document.querySelector(".axis-badge-drawing")).not.toBeNull();

  // Drag it down 40px with the cursor.
  fireEvent.pointerDown(scroller, { clientX: 500, clientY: 201, pointerId: 2 });
  fireEvent.pointerMove(scroller, { clientX: 500, clientY: 241, pointerId: 2 });
  fireEvent.pointerUp(scroller, { clientX: 500, clientY: 241, pointerId: 2 });
  expect(Number(levels()[0])).toBeCloseTo(240, 0);

  // Kept after a reload of the page.
  cleanup();
  renderPage();
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  expect(levels()).toHaveLength(1);

  // Select and delete with the keyboard.
  const again = document.querySelector(".flow-scroll") as HTMLElement;
  const y = Number(levels()[0]);
  fireEvent.pointerDown(again, { clientX: 500, clientY: y, pointerId: 3 });
  fireEvent.pointerUp(again, { clientX: 500, clientY: y, pointerId: 3 });
  fireEvent.keyDown(window, { key: "Delete" });
  expect(levels()).toEqual([]);
});

test("a trend line is drawn by dragging between two points, and the measure tool reads the move", async () => {
  localStorage.clear();
  renderPage();
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  const scroller = document.querySelector(".flow-scroll") as HTMLElement;
  fireEvent.click(screen.getByRole("button", { name: "Trend line" }));
  fireEvent.pointerDown(scroller, { clientX: 100, clientY: 300, pointerId: 1 });
  fireEvent.pointerMove(scroller, { clientX: 400, clientY: 150, pointerId: 1 });
  fireEvent.pointerUp(scroller, { clientX: 400, clientY: 150, pointerId: 1 });
  const line = document.querySelector(".drawings line.drawing") as SVGLineElement;
  const ends = ["x1", "y1", "x2", "y2"].map((name) => Math.round(Number(line.getAttribute(name))));
  expect(ends).toEqual([100, 300, 400, 150]);

  fireEvent.click(screen.getByRole("button", { name: "Measure" }));
  fireEvent.pointerDown(scroller, { clientX: 200, clientY: 300, pointerId: 2 });
  fireEvent.pointerMove(scroller, { clientX: 260, clientY: 200, pointerId: 2 });
  fireEvent.pointerUp(scroller, { clientX: 260, clientY: 200, pointerId: 2 });
  expect(document.querySelector(".drawing-measure-label")?.textContent).toMatch(
    /^\+[\d,.]+ \(\+[\d.]+%\) · \d+m$/,
  );

  fireEvent.click(screen.getByRole("button", { name: "Remove all drawings" }));
  expect(document.querySelectorAll(".drawings .drawing")).toHaveLength(0);
});

test("the current price is marked on the axis and the candle values show at the top", async () => {
  renderPage();
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  expect(document.querySelector(".last-price-line")).not.toBeNull();
  expect(document.querySelector(".axis-badge-last")).not.toBeNull();
  expect(document.querySelector(".chart-legend")?.textContent).toMatch(/NQZ6 · 1m.*O.*H.*L.*C/);
});

test("Fibonacci levels can be edited, hidden, recoloured, added, shaded and saved as the default", async () => {
  localStorage.clear();
  renderPage();
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  const scroller = document.querySelector(".flow-scroll") as HTMLElement;
  const drawFib = () => {
    fireEvent.click(screen.getByRole("button", { name: "Fib retracement" }));
    fireEvent.pointerDown(scroller, { clientX: 100, clientY: 100, pointerId: 1 });
    fireEvent.pointerMove(scroller, { clientX: 400, clientY: 300, pointerId: 1 });
    fireEvent.pointerUp(scroller, { clientX: 400, clientY: 300, pointerId: 1 });
  };
  const labels = () =>
    [...document.querySelectorAll(".drawings .drawing-label")].map((t) => t.textContent?.split(" ")[0]);
  drawFib();
  // The new drawing is selected, but its settings stay closed until asked for, so the chart stays clear.
  expect(screen.queryByRole("region", { name: "Fib retracement settings" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Drawing settings" }));
  const panel = screen.getByRole("region", { name: "Fib retracement settings" });
  // The standard levels, all shown.
  expect(labels()).toEqual([
    "0",
    "0.114",
    "0.236",
    "0.382",
    "0.5",
    "0.618",
    "0.786",
    "0.886",
    "1",
    "1.382",
    "1.618",
    "2",
    "2.618",
  ]);

  fireEvent.change(within(panel).getByLabelText("Level 6 ratio"), { target: { value: "0.65" } });
  expect(labels()).toContain("0.65");
  fireEvent.click(within(panel).getByLabelText("Show level 0.236"));
  expect(labels()).not.toContain("0.236");

  fireEvent.click(within(panel).getByRole("button", { name: "Level 1 colour" }));
  // The palette is drawn outside the panel, so the scrolling level list cannot clip it.
  const palette = screen.getByRole("group", { name: "Level 1 colour options" });
  expect(panel.contains(palette)).toBe(false);
  fireEvent.click(within(palette).getByRole("button", { name: "#d6409f" }));
  expect(screen.queryByRole("group", { name: "Level 1 colour options" })).toBeNull();
  // The last level's palette opens too, and closes on a click elsewhere.
  fireEvent.click(within(panel).getByRole("button", { name: "Level 9 colour" }));
  expect(screen.getByRole("group", { name: "Level 9 colour options" })).toBeInTheDocument();
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("group", { name: "Level 9 colour options" })).toBeNull();
  const first = document.querySelector(".drawings line.drawing-fib") as SVGLineElement;
  expect(first.style.stroke).toMatch(/#d6409f|rgb\(214, 64, 159\)/);

  fireEvent.click(within(panel).getByRole("button", { name: "Add level" }));
  expect(labels()).toContain("1.272");
  fireEvent.click(within(panel).getByLabelText("Background"));
  expect(document.querySelectorAll(".drawing-fib-band").length).toBeGreaterThan(0);

  // Saved as the default, a second Fibonacci drawing starts with the same levels.
  fireEvent.click(within(panel).getByRole("button", { name: "Save as default" }));
  fireEvent.click(within(panel).getByRole("button", { name: "Close settings" }));
  expect(screen.queryByRole("region", { name: "Fib retracement settings" })).toBeNull();
  // A double-click on the drawing opens them again.
  fireEvent.doubleClick(scroller, { clientX: 250, clientY: 200 });
  expect(screen.getByRole("region", { name: "Fib retracement settings" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
  const before = labels();
  drawFib();
  expect(labels()).toEqual([...before, ...before]);
});

test("zooming out past the fit reaches back over earlier one-minute candles", async () => {
  // Three days of one-minute candles before the overnight board, only while the market is open.
  const from = HISTORY.overnight.ts_ns - 3 * 24 * 60 * MINUTE;
  const hours = tradingTime(from - 24 * 60 * MINUTE, HISTORY.overnight.ts_ns + 24 * 60 * MINUTE);
  const early = Array.from({ length: 3 * 24 * 60 }, (_, i) => from + i * MINUTE)
    .filter((start_ns) => !hours.closed(start_ns) && !hours.closed(start_ns + MINUTE))
    .map((start_ns) => ({
      start_ns,
      open: 27_700,
      high: 27_710,
      low: 27_690,
      close: 27_705,
      volume: 1,
      trades: 1,
    }));
  mockFetch({
    "GET /api/gex/flow/dates": () => json(["2026-11-10"]),
    "GET /api/gex/flow/history": () => json(HISTORY),
    "GET /api/gex/bars": () => json([...early, ...BARS]),
  });
  render(
    <MemoryRouter>
      <FlowPage />
    </MemoryRouter>,
  );
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  const candles = () => document.querySelectorAll(".flow-scroll .candle").length;
  const fitted = candles();
  const scroller = document.querySelector(".flow-scroll") as HTMLElement;
  for (let i = 0; i < 40; i++) fireEvent.wheel(scroller, { deltaY: 400, clientX: 300 });
  // Every earlier one-minute candle comes into view.
  expect(early.length).toBeGreaterThan(1000);
  expect(candles()).toBeGreaterThanOrEqual(fitted + early.length);
  expect(
    [...document.querySelectorAll(".flow-scroll .axis-tick")].some((t) =>
      /^Nov \d+$/.test(t.textContent ?? ""),
    ),
  ).toBe(true);
});

test("the chart reopens at the zoom and price range it was left at", async () => {
  renderPage();
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  const scroller = document.querySelector(".flow-scroll") as HTMLElement;
  fireEvent.wheel(scroller, { deltaY: -600, clientX: 100 });
  fireEvent.pointerDown(scroller, { clientX: 300, clientY: 200, pointerId: 1 });
  fireEvent.pointerMove(scroller, { clientX: 300, clientY: 320, pointerId: 1 });
  fireEvent.pointerUp(scroller, { clientX: 300, clientY: 320, pointerId: 1 });
  fireEvent.pointerLeave(scroller);
  const width = screen.getByRole("img", { name: /flow nodes/ }).getAttribute("width");
  const ticks = () =>
    [...document.querySelectorAll(".flow-axis .axis-tick")].map((t) => t.textContent).join(",");
  const panned = ticks();
  await waitFor(() => expect(localStorage.getItem("lrl.flow.view.NQZ6.2026-11-10")).not.toBeNull());
  cleanup();
  renderPage();
  const again = await screen.findByRole("img", { name: /flow nodes/ });
  expect(again.getAttribute("width")).toBe(width);
  expect(ticks()).toBe(panned);
});

test("earlier sessions from the past week are drawn as nodes on their own day", async () => {
  const DAY = 24 * 60 * MINUTE;
  const earlier = {
    ...HISTORY,
    expiry: "20261109",
    session_date: "2026-11-09",
    ratio: 41.2,
    frames: HISTORY.frames.map((frame) => ({ ...frame, ts_ns: frame.ts_ns - DAY })),
  };
  // Candles from the day before too, so zooming out can reach it.
  const before = BARS.map((bar) => ({ ...bar, start_ns: bar.start_ns - DAY - 60 * MINUTE }));
  const calls = mockFetch({
    "GET /api/gex/flow/dates": () => json(["2026-11-02", "2026-11-09", "2026-11-10"]),
    "GET /api/gex/flow/history": (request) =>
      json(new URL(request.url).searchParams.get("date") === "2026-11-09" ? earlier : HISTORY),
    "GET /api/gex/bars": () => json([...before, ...BARS]),
  });
  render(
    <MemoryRouter>
      <FlowPage />
    </MemoryRouter>,
  );
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  expect(document.querySelectorAll(".flow-dot-past")).toHaveLength(0);
  const scroller = document.querySelector(".flow-scroll") as HTMLElement;
  await waitFor(() => {
    fireEvent.wheel(scroller, { deltaY: 2000, clientX: 300 });
    expect(document.querySelectorAll(".flow-dot-past").length).toBeGreaterThan(0);
  });
  // Only sessions within the week are fetched (Nov 2 is more than a week before Nov 10).
  const dates = calls.flatMap((call) => new URL(call.url).searchParams.get("date") ?? []);
  expect(dates).toContain("2026-11-09");
  expect(dates).not.toContain("2026-11-02");
});

test("the node table sorts by a column heading, reverses on a second click, and remembers it", async () => {
  renderPage();
  const table = await screen.findByRole("table", { name: /flow nodes/ });
  const strikes = () =>
    within(screen.getByRole("table", { name: /flow nodes/ }))
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("cell")[1]?.textContent);
  const ranks = () =>
    within(screen.getByRole("table", { name: /flow nodes/ }))
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("cell")[0]?.textContent);
  // Strongest first by default.
  expect(strikes()).toEqual(["674", "671", "680"]);

  await userEvent.click(within(table).getByRole("button", { name: "QQQ" }));
  expect(strikes()).toEqual(["680", "674", "671"]);
  // The # column keeps each node's strength rank.
  expect(ranks()).toEqual(["3", "★", "2"]);
  expect(within(table).getByRole("columnheader", { name: /QQQ/ })).toHaveAttribute("aria-sort", "descending");
  await userEvent.click(within(table).getByRole("button", { name: "QQQ" }));
  expect(strikes()).toEqual(["671", "674", "680"]);

  // Futures orders like the strike, but only the clicked column is marked.
  await userEvent.click(within(table).getByRole("button", { name: "Futures" }));
  expect(strikes()).toEqual(["680", "674", "671"]);
  expect(within(table).getByRole("columnheader", { name: /Futures/ })).toHaveAttribute(
    "aria-sort",
    "descending",
  );
  expect(within(table).getByRole("columnheader", { name: /QQQ/ })).toHaveAttribute("aria-sort", "none");

  await userEvent.click(within(table).getByRole("button", { name: "Value" }));
  expect(strikes()).toEqual(["680", "671", "674"]);

  cleanup();
  renderPage();
  await screen.findByRole("table", { name: /flow nodes/ });
  expect(strikes()).toEqual(["680", "671", "674"]);
});

test("filters load the matching node set, the axis option is display only, and choices are remembered", async () => {
  const calls = renderPage();
  await screen.findByRole("img", { name: /flow nodes for 2 minutes/ });
  const historyUrls = () =>
    calls.filter((call) => call.url.includes("/flow/history")).map((call) => new URL(call.url).search);
  expect(historyUrls().at(-1)).not.toContain("skip_");

  await userEvent.click(screen.getByRole("button", { name: "Filters" }));
  await userEvent.click(screen.getByLabelText(/Skip trades inside the spread/));
  await waitFor(() => expect(historyUrls().at(-1)).toContain("skip_inside=false"));
  expect(historyUrls().at(-1)).not.toContain("skip_locked");
  await userEvent.click(screen.getByLabelText(/Skip locked or crossed quotes/));
  await waitFor(() => expect(historyUrls().at(-1)).toContain("skip_locked=false"));
  expect(screen.getByRole("button", { name: "Filters · 2 changed" })).toBeInTheDocument();

  const requests = calls.length;
  await userEvent.click(screen.getByLabelText(/Hide axis prices under price tags/));
  expect(calls.length).toBe(requests);

  cleanup();
  const again = renderPage();
  await screen.findByRole("img", { name: /flow nodes/ });
  expect(again.find((call) => call.url.includes("/flow/history"))?.url).toContain(
    "skip_inside=false&skip_locked=false",
  );
  expect(screen.getByRole("button", { name: "Filters · 3 changed" })).toBeInTheDocument();
});

test("the guide opens on a first visit and stays closed once closed", async () => {
  renderPage();
  await screen.findByRole("img", { name: /flow nodes/ });
  expect(screen.getByRole("region", { name: "How to read flow nodes" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Close the guide" }));
  expect(screen.queryByRole("region", { name: "How to read flow nodes" })).toBeNull();
  cleanup();
  renderPage();
  await screen.findByRole("img", { name: /flow nodes/ });
  expect(screen.queryByRole("region", { name: "How to read flow nodes" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "How to read" }));
  expect(screen.getByRole("region", { name: "How to read flow nodes" })).toBeInTheDocument();
});

test("a Korean cheat sheet sits under the node table and remembers if it was folded", async () => {
  renderPage();
  await screen.findByRole("table", { name: /flow nodes/ });
  const sheet = screen.getByText("노드 치트시트").closest("details") as HTMLDetailsElement;
  expect(sheet.open).toBe(true);
  expect(screen.getByRole("table", { name: "상승 중일 때" })).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "하락 중일 때" })).toBeInTheDocument();
  sheet.open = false;
  fireEvent(sheet, new Event("toggle"));
  cleanup();
  renderPage();
  await screen.findByRole("table", { name: /flow nodes/ });
  expect((screen.getByText("노드 치트시트").closest("details") as HTMLDetailsElement).open).toBe(false);
});
