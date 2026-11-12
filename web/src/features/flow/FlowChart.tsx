import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useElementWidth } from "../../lib/useElementWidth";
import { formatGex, formatPrice } from "../gex/format";
import { niceTicks } from "../gex/scale";
import { combine, frameAt } from "./bars";
import { DrawingToolbar } from "./DrawingToolbar";
import { FibSettings } from "./FibSettings";
import {
  fibPrice,
  measure,
  moved,
  newId,
  pick as pickDrawing,
  rayEnd,
  useDrawings,
  useFibDefaults,
  visibleLevels,
  type Drawing,
  type Point,
  type Projection,
  type Tool,
  type TwoPointKind,
} from "./drawings";
import { tradingTime } from "./tradingTime";
import { formatDay, formatTime, nyHour, topNodes, type Bar, type NodeFrame } from "./useFlowHistory";

const MARGIN = { top: 12, right: 72, bottom: 28, left: 8 };
const TOOLBAR = 40;
const MINUTE = 60_000_000_000;
const HOUR = 60 * MINUTE;
const MAX_ZOOM = 16;
/** White reads only on a dark surface; on the light theme it is drawn in the text colour. */
function ink(color: string): string {
  return color.toLowerCase() === "#ffffff" ? "var(--text)" : color;
}

type SavedView = {
  zoom: number;
  priceView: { top: number; bottom: number } | null;
  /** Following the latest minute: its distance from the right edge, in pixels. */
  gap: number | null;
  /** Otherwise the time at the right edge. */
  right: number | null;
};

function readView(key: string): SavedView | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as SavedView) : null;
  } catch {
    return null;
  }
}

function writeView(key: string, view: SavedView) {
  try {
    localStorage.setItem(key, JSON.stringify(view));
  } catch {
    // Without storage the chart opens at its default position next time.
  }
}

/** selected is a frame index, or OVERNIGHT for the board shown before the open. */
export const OVERNIGHT = -1;

/**
 * Futures candles with the ETF's flow nodes replayed over time: each minute, the strongest nodes
 * are drawn as dots at their futures price, sized by strength, so nodes can be seen forming and
 * fading through the session. Hovering picks the minute shown in the node table.
 *
 * Drag to scroll through time and pan prices, use the wheel (or a pinch) to zoom around the
 * pointer, drag the price axis to stretch prices, and double-click to fit everything again. The
 * tool bar on the left draws lines, boxes, Fibonacci levels and measurements, kept per symbol.
 */
export function FlowChart({
  bars: allBars,
  frames,
  ratio,
  overnight = null,
  overnightRatio = null,
  windowStart,
  showWalls = true,
  showFlip = true,
  follow = false,
  initialZoom = 2,
  count,
  selected,
  onSelect,
  height,
  storageKey = "lrl.flow.drawings",
  label = "",
  interval = 1,
  hideTicksUnderTags = true,
  frameStep = MINUTE,
  tickSize = 0.25,
  showSecond = true,
  past = [],
  viewKey,
}: {
  bars: Bar[];
  frames: NodeFrame[];
  ratio: number;
  /** The board frozen from the previous close until the open, drawn as flat stripes. */
  overnight?: NodeFrame | null;
  overnightRatio?: number | null;
  windowStart: number;
  /** Draw the call and put walls as lines that move minute by minute. */
  showWalls?: boolean;
  /** Draw the gamma flip the same way. */
  showFlip?: boolean;
  /** Live: keep the latest minute in view while the user is at the right edge. */
  follow?: boolean;
  /** Starting horizontal zoom: 1 fits the window; above 1 the chart scrolls sideways. */
  initialZoom?: number;
  count: number;
  selected: number;
  /** A minute's index, OVERNIGHT, or null for "the latest" (live keeps following it). */
  onSelect: (index: number | null) => void;
  height: number;
  /** Where this chart's drawings are kept (per symbol). */
  storageKey?: string;
  /** Shown before the candle values, e.g. "NQZ6 · 1m". */
  label?: string;
  /** Candle length in minutes, chosen by the user. */
  interval?: number;
  /** Hide price-axis labels behind the current-price and crosshair tags. */
  hideTicksUnderTags?: boolean;
  /** Market time each frame covers: a minute, or 10 seconds when streaming. */
  frameStep?: number;
  /** The future's price increment: the crosshair and drawings snap to it (0.25 for NQ). */
  tickSize?: number;
  /** Ring the second-strongest node too, in a lighter style than the king. */
  showSecond?: boolean;
  /** Earlier sessions' frames, drawn as dots over their own days when zoomed out. */
  past?: { frames: NodeFrame[]; ratio: number }[];
  /** Where this view's zoom, prices and scroll position are kept between visits. */
  viewKey?: string;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const scroller = useRef<HTMLDivElement>(null);
  const plot = useRef<SVGSVGElement>(null);
  // The last zoom, price range and position for this view, read once when the chart opens.
  const [saved] = useState(() => (viewKey ? readView(viewKey) : null));
  const [zoom, setZoom] = useState(saved?.zoom ?? initialZoom);
  // Where the pointer was, as a share of the plot, so a zoom keeps that minute under it.
  const anchor = useRef<{ share: number; offset: number } | null>(null);
  const drag = useRef<{
    x: number;
    y: number;
    scroll: number;
    top: number;
    bottom: number;
    moved: boolean;
  } | null>(null);
  const axisDrag = useRef<{ y: number; top: number; bottom: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  // A price range the user has panned or stretched to; null follows the data automatically.
  const [priceView, setPriceView] = useState<{ top: number; bottom: number } | null>(
    saved?.priceView ?? null,
  );
  // Live: how far the latest minute sits from the view's right edge, kept as new minutes arrive.
  // null once the user scrolls the latest minute out of view.
  const followGap = useRef<number | null>(null);
  const viewWidth = Math.max(width - MARGIN.right - TOOLBAR, 0);
  // Above 1 the plot grows and scrolls; below 1 it stays one view wide and reaches further back.
  const plotRight = MARGIN.left + Math.max(viewWidth - MARGIN.left, 100) * Math.max(zoom, 1);
  // Blank space after the latest minute, so it can be dragged to the middle of the view.
  const rightSpace = Math.round(viewWidth * 0.5);
  // Drawing state: the chosen tool, the drawing in progress, the selected one, and one being moved.
  const { drawings, add, replace, remove, clear } = useDrawings(storageKey);
  const fibDefaults = useFibDefaults();
  const [tool, setTool] = useState<Tool>("cursor");
  const [hidden, setHidden] = useState(false);
  const [draft, setDraft] = useState<{ kind: TwoPointKind; a: Point; b: Point } | null>(null);
  const draftPress = useRef<{ x: number; y: number } | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  // Settings open only on request (the bar's Settings button or a double-click), never on select.
  const [settingsFor, setSettingsFor] = useState<string | null>(null);
  const moving = useRef<{ origin: Point; original: Drawing } | null>(null);
  // The pointer in plot coordinates, for the crosshair; null when it is off the chart.
  const [hover, setHover] = useState<{ cx: number; cy: number } | null>(null);
  const plotBottom = height - MARGIN.bottom;
  const open = (frames[0]?.ts_ns ?? 0) - MINUTE;
  const fitStart = Math.min(windowStart, open);
  // The forming candle can run ahead of the latest frame by a few seconds.
  // Snapped to the end of the minute, so the time scale (and every candle's x) only moves once a
  // minute rather than with every frame.
  const end =
    Math.ceil(
      Math.max(frames.at(-1)?.ts_ns ?? fitStart + MINUTE, (allBars.at(-1)?.start_ns ?? 0) + MINUTE) / MINUTE,
    ) * MINUTE;
  // Zooming out past the fit reaches back to the earliest loaded candle.
  const earliest = Math.min(fitStart, allBars[0]?.start_ns ?? fitStart);
  // Time on screen is trading time: the daily close and the weekend take no width.
  const day = 24 * HOUR;
  const rangeFrom = Math.floor(earliest / day) * day - day;
  const rangeTo = Math.ceil(end / day) * day + 2 * day;
  const tt = useMemo(() => tradingTime(rangeFrom, rangeTo), [rangeFrom, rangeTo]);
  const C = tt.compress;
  const minZoom = Math.min(1, (C(end) - C(fitStart)) / Math.max(C(end) - C(earliest), 1));
  const minZoomRef = useRef(minZoom);
  useLayoutEffect(() => {
    minZoomRef.current = minZoom;
  }, [minZoom]);
  const start =
    zoom >= 1
      ? fitStart
      : Math.max(earliest, tt.expand(C(end) - (C(end) - C(fitStart)) / Math.max(zoom, minZoom)));
  const cStart = C(start);
  const cSpan = Math.max(C(end) - cStart, 1);
  const bars = useMemo(
    () =>
      combine(
        allBars.filter((bar) => bar.start_ns >= start),
        interval,
      ),
    [allBars, start, interval],
  );
  const span = interval * MINUTE;
  const x = (ns: number) => MARGIN.left + ((C(ns) - cStart) / cSpan) * (plotRight - MARGIN.left);

  // Dots per frame: thin frames out so dots stay at least 3px apart.
  const stride = Math.max(1, Math.ceil(3 / ((plotRight - MARGIN.left) / Math.max(frames.length, 1))));
  const dots = useMemo(
    () =>
      frames.flatMap((frame, index) => {
        if (index % stride !== 0 && index !== frames.length - 1) return [];
        const nodes = topNodes(frame, count);
        const king = Math.abs(nodes[0]?.value ?? 0) || 1;
        return nodes.map((node, rank) => ({
          key: `${frame.ts_ns}-${node.strike}`,
          ns: frame.ts_ns,
          price: node.strike * ratio,
          share: Math.abs(node.value) / king,
          positive: node.value >= 0,
          king: rank === 0,
          second: rank === 1,
        }));
      }),
    [frames, count, ratio, stride],
  );

  // Earlier sessions, thinned the same way: one frame every few pixels.
  const minuteStride = Math.max(1, Math.ceil(3 / ((plotRight - MARGIN.left) / Math.max(cSpan / MINUTE, 1))));
  const pastDots = useMemo(
    () =>
      past.flatMap((session) =>
        session.frames.flatMap((frame, index) => {
          if (index % minuteStride !== 0 || frame.ts_ns < start) return [];
          const nodes = topNodes(frame, count);
          const king = Math.abs(nodes[0]?.value ?? 0) || 1;
          return nodes.map((node, rank) => ({
            key: `p-${frame.ts_ns}-${node.strike}`,
            past: true,
            ns: frame.ts_ns,
            price: node.strike * session.ratio,
            share: Math.abs(node.value) / king,
            positive: node.value >= 0,
            king: rank === 0,
            second: rank === 1,
          }));
        }),
      ),
    [past, count, minuteStride, start],
  );

  // Overnight stripes: the frozen board from the previous close, repeated every 4px until the open.
  const stripes = useMemo(() => {
    if (!overnight || !overnightRatio || start >= open) return [];
    const from = Math.max(start, overnight.ts_ns);
    // Spaced evenly on screen, which is trading time, so the weekend adds no stripes.
    const spacing = ((zoom > 2 ? 6 : 4) / Math.max(plotRight - MARGIN.left, 1)) * cSpan;
    const nodes = topNodes(overnight, count);
    const king = Math.abs(nodes[0]?.value ?? 0) || 1;
    const times: number[] = [];
    for (let t = C(from); t < C(open); t += spacing) times.push(tt.expand(t));
    return nodes.flatMap((node, rank) =>
      times.map((ns) => ({
        key: `o-${node.strike}-${ns}`,
        ns,
        price: node.strike * overnightRatio,
        share: Math.abs(node.value) / king,
        positive: node.value >= 0,
        king: rank === 0,
        second: rank === 1,
      })),
    );
    // C is tt.compress.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overnight, overnightRatio, start, open, end, count, plotRight, zoom, tt, cSpan]);

  const prices = [
    ...bars.flatMap((bar) => [bar.low, bar.high]),
    ...[...dots, ...stripes].filter((dot) => dot.share >= 0.25).map((dot) => dot.price),
  ];
  const low = Math.min(...prices);
  const high = Math.max(...prices);
  const pad = (high - low) * 0.04 || 10;
  const top = priceView?.top ?? high + pad;
  const bottom = priceView?.bottom ?? low - pad;
  const y = (price: number) => MARGIN.top + ((top - price) / (top - bottom)) * (plotBottom - MARGIN.top);
  const priceTicks = niceTicks(bottom, top, 8);
  const nsAt = (cx: number) => tt.expand(cStart + ((cx - MARGIN.left) / (plotRight - MARGIN.left)) * cSpan);
  const rawPriceAt = (cy: number) => top - ((cy - MARGIN.top) / (plotBottom - MARGIN.top)) * (top - bottom);
  const snap = (price: number) => Math.round(price / tickSize) * tickSize;
  // Prices read from the pointer land on the futures tick grid, like real prices.
  const priceAt = (cy: number) => snap(rawPriceAt(cy));
  const projection: Projection = { x, y, right: plotRight + rightSpace };
  const lastBar = bars.at(-1);
  const hoverNs = hover ? nsAt(hover.cx) : null;
  // Candles are drawn at the end of their interval; the hovered one is the candle under the pointer.
  const hoveredBar =
    hoverNs === null
      ? null
      : (bars.find((bar) => hoverNs <= bar.start_ns + span && hoverNs > bar.start_ns) ?? null);
  const legendBar = hoveredBar ?? lastBar ?? null;

  // Each level as a step line through the session, broken where it doesn't exist; flat overnight.
  function levelPath(key: "call_wall" | "put_wall" | "flip"): string {
    const parts: string[] = [];
    let drawing = false;
    let lastPrice: number | null = null;
    const visible = (price: number) => price >= bottom && price <= top;
    if (overnight && overnightRatio && start < open && overnight[key] != null) {
      const price = (overnight[key] ?? 0) * overnightRatio;
      if (visible(price)) parts.push(`M${x(Math.max(start, overnight.ts_ns))},${y(price)}H${x(open)}`);
    }
    for (const frame of frames) {
      const level = frame[key];
      const price = level == null ? null : level * ratio;
      if (price == null || !visible(price)) {
        drawing = false;
        continue;
      }
      // Walls jump between strikes: draw only their flat runs so the jumps don't clutter the chart.
      // The flip moves smoothly, so it stays one connected line.
      const joined = drawing && (key === "flip" || price === lastPrice);
      parts.push(
        joined
          ? `H${x(frame.ts_ns)}V${y(price)}`
          : `M${x(frame.ts_ns - MINUTE)},${y(price)}H${x(frame.ts_ns)}`,
      );
      drawing = true;
      lastPrice = price;
    }
    return parts.join("");
  }
  // Whole-hour labels in New York time at least ~110px apart; midnight is labelled with the date.
  const hours = cSpan / HOUR;
  const fit = Math.max((plotRight - MARGIN.left) / 110, 2);
  const every = [1, 2, 3, 4, 6, 12].find((step) => hours / step <= fit) ?? 24;
  const hourTicks: number[] = [];
  for (let ns = Math.ceil(start / HOUR) * HOUR; ns <= end; ns += HOUR) {
    // Skip labels that would be clipped at either edge of the plot.
    const edge = 28;
    // Hours while the market is shut have no width; the reopening hour shares the close's spot.
    if (tt.closed(ns) || tt.closed(ns - 1)) continue;
    if (nyHour(ns) % every === 0 && x(ns) > MARGIN.left + edge && x(ns) < plotRight - edge)
      hourTicks.push(ns);
  }
  const current = selected === OVERNIGHT ? null : frames[selected];

  const plotWidth = plotRight - MARGIN.left;
  const opened = useRef(false);
  // Keep the view (zoom, prices, and either the follow gap or the time at the right edge) a moment
  // after it stops changing.
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  function remember() {
    const box = scroller.current;
    if (!viewKey || !box || !opened.current) return;
    clearTimeout(saveTimer.current);
    const view: SavedView = {
      zoom: Math.max(zoom, minZoom),
      priceView,
      gap: follow ? followGap.current : null,
      right: nsAt(box.scrollLeft + box.clientWidth),
    };
    saveTimer.current = setTimeout(() => writeView(viewKey, view), 250);
  }
  useEffect(() => {
    remember();
    // Saved when the zoom or the price range changes; remember reads the rest.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoom, priceView]);
  useEffect(() => () => clearTimeout(saveTimer.current), []);
  useLayoutEffect(() => {
    const box = scroller.current;
    if (!box || width === 0) return;
    // Wait for the candles: zoomed out, the time range (and so any saved position) depends on them.
    if (!opened.current && !allBars.length) return;
    if (anchor.current) {
      box.scrollLeft = MARGIN.left + anchor.current.share * plotWidth - anchor.current.offset;
      anchor.current = null;
    } else if (!opened.current) {
      // Back where the user left it: following the latest at the same spot, or at the same time.
      // Otherwise live starts with the latest minute near the right and a past session at the open.
      if (saved && follow && saved.gap !== null) {
        followGap.current = saved.gap;
        box.scrollLeft = x(end) + saved.gap - box.clientWidth;
      } else if (saved && saved.right !== null) {
        followGap.current = null;
        box.scrollLeft = x(saved.right) - box.clientWidth;
        const latest = x(end);
        if (follow && latest >= box.scrollLeft && latest <= box.scrollLeft + box.clientWidth)
          followGap.current = box.scrollLeft + box.clientWidth - latest;
      } else {
        if (follow) followGap.current = box.clientWidth * 0.15;
        box.scrollLeft = follow
          ? x(end) + (followGap.current ?? 0) - box.clientWidth
          : Math.max(x(open) - box.clientWidth * 0.15, 0);
      }
      opened.current = true;
    }
    // x and open are derived from the same inputs as plotWidth.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plotWidth, width, allBars.length > 0]);

  // Live: as new minutes arrive, keep the latest one where the user left it on screen.
  useLayoutEffect(() => {
    const box = scroller.current;
    if (box && follow && followGap.current !== null)
      box.scrollLeft = x(end) + followGap.current - box.clientWidth;
    // x follows end and the plot width.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [end, follow, plotWidth]);

  useEffect(() => {
    const box = scroller.current;
    if (!box) return;
    function onWheel(event: WheelEvent) {
      const element = box as HTMLDivElement;
      // A sideways trackpad swipe scrolls natively; vertical wheel and pinch (ctrl) zoom.
      if (!event.ctrlKey && Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
      event.preventDefault();
      const offset = event.clientX - element.getBoundingClientRect().left;
      anchor.current = { share: (element.scrollLeft + offset - MARGIN.left) / plotWidth, offset };
      setZoom((current) => {
        const next = Math.min(
          Math.max(current * Math.exp(-event.deltaY * 0.0015), minZoomRef.current),
          MAX_ZOOM,
        );
        // Below 1 the plot keeps its width and its right edge, so there is nothing to anchor.
        if (next < 1) anchor.current = null;
        return next;
      });
    }
    box.addEventListener("wheel", onWheel, { passive: false });
    return () => box.removeEventListener("wheel", onWheel);
  }, [plotWidth]);

  const viewRight = plotRight + rightSpace;
  // Thousands of candles when zoomed out. They are drawn in minutes (from a fixed origin) and price
  // units, and placed with one transform, so scrolling, zooming, the minute ticking over and node
  // updates that move the price scale change one attribute instead of every candle. Finished
  // candles are kept between renders; only the forming one is drawn again.
  const origin = Math.floor((allBars[0]?.start_ns ?? fitStart) / (24 * HOUR)) * 24 * HOUR;
  const candle = (bar: Bar) => {
    const cx = (C(bar.start_ns + span) - C(origin)) / MINUTE;
    const up = bar.close >= bar.open;
    return (
      <g key={bar.start_ns} className={up ? "candle candle-up" : "candle candle-down"}>
        <line x1={cx} x2={cx} y1={bar.high} y2={bar.low} />
        <rect
          x={cx - interval * 0.3}
          y={Math.min(bar.open, bar.close)}
          width={interval * 0.6}
          height={Math.max(Math.abs(bar.close - bar.open), 1e-6)}
        />
      </g>
    );
  };
  const settled = bars.length > 1 ? bars[bars.length - 2] : undefined;
  const settledKey = `${bars.length}:${bars[0]?.start_ns}:${settled?.start_ns}:${settled?.close}`;
  const settledCandles = useMemo(
    () => bars.slice(0, -1).map(candle),
    // Finished candles change only when one is added or the first in view changes; settledKey
    // tracks the count, the first and the newest finished one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [settledKey, origin, span, interval, tt],
  );
  const perNs = (plotRight - MARGIN.left) / cSpan;
  const pricePx = (plotBottom - MARGIN.top) / (top - bottom);
  const candleTransform = `matrix(${MINUTE * perNs} 0 0 ${-pricePx} ${MARGIN.left + (C(origin) - cStart) * perNs} ${MARGIN.top + top * pricePx})`;
  const chosenDrawing = drawings.find((drawing) => drawing.id === chosen);
  const chosenFib = chosenDrawing?.kind === "fib" ? chosenDrawing : null;

  function shape(drawing: Drawing, isChosen: boolean) {
    const cls = isChosen ? "drawing drawing-chosen" : "drawing";
    if (drawing.kind === "hline") {
      const py = y(drawing.price);
      return <line className={cls} x1={MARGIN.left} x2={viewRight} y1={py} y2={py} />;
    }
    if (drawing.kind === "vline") {
      const px = x(drawing.ns);
      return <line className={cls} x1={px} x2={px} y1={MARGIN.top} y2={plotBottom} />;
    }
    const ax = x(drawing.a.ns);
    const ay = y(drawing.a.price);
    const bx = x(drawing.b.ns);
    const by = y(drawing.b.price);
    const handles = isChosen ? (
      <>
        <circle className="drawing-handle" cx={ax} cy={ay} r={4} />
        <circle className="drawing-handle" cx={bx} cy={by} r={4} />
      </>
    ) : null;
    const left = Math.min(ax, bx);
    const boxWidth = Math.abs(bx - ax);
    if (drawing.kind === "trend" || drawing.kind === "ray") {
      const [ex, ey] = drawing.kind === "ray" ? rayEnd(ax, ay, bx, by, viewRight, MARGIN.left) : [bx, by];
      return (
        <>
          <line className={cls} x1={ax} y1={ay} x2={ex} y2={ey} />
          {handles}
        </>
      );
    }
    if (drawing.kind === "rect") {
      return (
        <>
          <rect
            className={`${cls} drawing-box`}
            x={left}
            y={Math.min(ay, by)}
            width={boxWidth}
            height={Math.abs(by - ay)}
          />
          {handles}
        </>
      );
    }
    if (drawing.kind === "fib") {
      const levels = visibleLevels(drawing.fib);
      const ys = levels.map((level) => y(fibPrice(drawing.a, drawing.b, level.value)));
      return (
        <>
          {drawing.fib?.fill &&
            levels.slice(1).map((level, index) => {
              const top = Math.min(ys[index] ?? 0, ys[index + 1] ?? 0);
              return (
                <rect
                  key={`band-${level.value}`}
                  className="drawing-fib-band"
                  x={left}
                  y={top}
                  width={boxWidth}
                  height={Math.abs((ys[index + 1] ?? 0) - (ys[index] ?? 0))}
                  style={{ fill: ink(level.color) }}
                />
              );
            })}
          {levels.map((level, index) => (
            <g key={`${level.value}-${index}`}>
              <line
                className={`${cls} drawing-fib`}
                x1={left}
                x2={left + boxWidth}
                y1={ys[index]}
                y2={ys[index]}
                style={{ stroke: ink(level.color) }}
              />
              <text
                className="drawing-label"
                x={left + 4}
                y={(ys[index] ?? 0) - 3}
                style={{ fill: ink(level.color) }}
              >
                {level.value} ({formatPrice(snap(fibPrice(drawing.a, drawing.b, level.value)))})
              </text>
            </g>
          ))}
          {handles}
        </>
      );
    }
    // Measure: the box between the points, with change, percent and minutes.
    const result = measure(drawing.a, drawing.b);
    const up = result.change >= 0;
    const sign = up ? "+" : "−";
    return (
      <>
        <rect
          className={`${cls} drawing-measure ${up ? "drawing-measure-up" : "drawing-measure-down"}`}
          x={left}
          y={Math.min(ay, by)}
          width={boxWidth}
          height={Math.abs(by - ay)}
        />
        <text
          className="drawing-label drawing-measure-label"
          x={left + boxWidth / 2}
          y={Math.min(ay, by) - 6}
          textAnchor="middle"
        >
          {sign}
          {formatPrice(Math.abs(result.change))} ({sign}
          {Math.abs(result.percent).toFixed(2)}%) · {Math.abs(result.minutes)}m
        </text>
        {handles}
      </>
    );
  }

  /** Pointer position in plot coordinates (the scrolled content, not the window). */
  function local(event: { clientX: number; clientY: number }) {
    const box = plot.current?.getBoundingClientRect();
    return { cx: event.clientX - (box?.left ?? 0), cy: event.clientY - (box?.top ?? 0) };
  }

  function finish(id: string) {
    setChosen(id);
    setDraft(null);
    setTool("cursor");
  }

  function commit(done: { kind: TwoPointKind; a: Point; b: Point }) {
    const id = newId();
    // A new Fibonacci drawing copies the saved defaults, so later default changes leave it alone.
    add(done.kind === "fib" ? { id, ...done, fib: fibDefaults.defaults } : { id, ...done });
    finish(id);
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && /INPUT|SELECT|TEXTAREA/.test(target.tagName)) return;
      if (event.key === "Escape") {
        setDraft(null);
        setTool("cursor");
        setChosen(null);
      } else if ((event.key === "Delete" || event.key === "Backspace") && chosen) {
        remove(chosen);
        setChosen(null);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [chosen, remove]);

  function pick(clientX: number) {
    if (!plot.current) return;
    const box = plot.current.getBoundingClientRect();
    const ns = nsAt(clientX - box.left);
    if (overnight && ns < open) {
      onSelect(OVERNIGHT);
      return;
    }
    // The latest frame at or before the pointer's minute, found by time: frames can skip minutes,
    // and counting minutes from the first frame would then show a later minute's nodes.
    const clamped = Math.max(frameAt(frames, Math.floor(ns / frameStep) * frameStep + frameStep - 1), 0);
    // Live: pointing at the latest minute means "follow the latest", so the table keeps updating.
    onSelect(follow && clamped === frames.length - 1 ? null : clamped);
  }

  return (
    <div className="flow-chart" ref={ref}>
      <DrawingToolbar
        tool={tool}
        onTool={(next) => {
          setTool(next);
          setDraft(null);
        }}
        hidden={hidden}
        onToggleHidden={() => setHidden((value) => !value)}
        onClear={() => {
          clear();
          setChosen(null);
        }}
        count={drawings.length}
      />
      <div
        className={["flow-scroll", dragging ? "flow-dragging" : "", tool !== "cursor" ? "flow-drawing" : ""]
          .filter(Boolean)
          .join(" ")}
        ref={scroller}
        onScroll={(event) => {
          const box = event.currentTarget;
          const latest = x(end);
          const inView = latest >= box.scrollLeft && latest <= box.scrollLeft + box.clientWidth;
          followGap.current = follow && inView ? box.scrollLeft + box.clientWidth - latest : null;
          remember();
        }}
        onPointerDown={(event) => {
          const at = local(event);
          const point = { ns: nsAt(at.cx), price: priceAt(at.cy) };
          if (tool === "hline" || tool === "vline") {
            const id = newId();
            add(
              tool === "hline"
                ? { id, kind: "hline", price: point.price }
                : { id, kind: "vline", ns: point.ns },
            );
            finish(id);
            return;
          }
          if (tool !== "cursor") {
            // Two-point tools: press sets the first point; release after a drag, or a second click, sets the other.
            if (draft) commit({ ...draft, b: point });
            else {
              setDraft({ kind: tool, a: point, b: point });
              draftPress.current = { x: event.clientX, y: event.clientY };
            }
            event.currentTarget.setPointerCapture?.(event.pointerId);
            return;
          }
          const hit = hidden ? null : pickDrawing(drawings, at.cx, at.cy, projection);
          if (hit) {
            setChosen(hit.id);
            moving.current = { origin: point, original: hit };
            event.currentTarget.setPointerCapture?.(event.pointerId);
            return;
          }
          setChosen(null);
          drag.current = {
            x: event.clientX,
            y: event.clientY,
            scroll: event.currentTarget.scrollLeft,
            top,
            bottom,
            moved: false,
          };
          event.currentTarget.setPointerCapture?.(event.pointerId);
          setDragging(true);
        }}
        onPointerMove={(event) => {
          const at = local(event);
          setHover(at);
          if (draft) {
            setDraft({ ...draft, b: { ns: nsAt(at.cx), price: priceAt(at.cy) } });
            return;
          }
          if (moving.current) {
            const { origin, original } = moving.current;
            replace(moved(original, nsAt(at.cx) - origin.ns, priceAt(at.cy) - origin.price));
            return;
          }
          const state = drag.current;
          if (!state) {
            pick(event.clientX);
            return;
          }
          const dx = event.clientX - state.x;
          const dy = event.clientY - state.y;
          if (Math.abs(dx) > 3 || Math.abs(dy) > 3) state.moved = true;
          if (!state.moved) return;
          // Sideways scrolls through time; up and down pans prices.
          event.currentTarget.scrollLeft = state.scroll - dx;
          const shift = dy * ((state.top - state.bottom) / Math.max(plotBottom - MARGIN.top, 1));
          setPriceView({ top: state.top + shift, bottom: state.bottom + shift });
        }}
        onPointerUp={(event) => {
          const press = draftPress.current;
          draftPress.current = null;
          if (draft && press && Math.hypot(event.clientX - press.x, event.clientY - press.y) > 4) {
            const at = local(event);
            commit({ ...draft, b: { ns: nsAt(at.cx), price: priceAt(at.cy) } });
          }
          moving.current = null;
          // A press without a drag is a click: select that minute.
          if (drag.current && !drag.current.moved) pick(event.clientX);
          drag.current = null;
          setDragging(false);
        }}
        onPointerCancel={() => {
          drag.current = null;
          moving.current = null;
          setDragging(false);
        }}
        onPointerLeave={() => {
          setHover(null);
          // Live: leaving the chart returns the table to the latest minute.
          if (follow && !drag.current) onSelect(null);
        }}
        onDoubleClick={(event) => {
          // Double-clicking a Fibonacci drawing opens its settings; anywhere else fits the chart.
          const at = local(event);
          const hit = hidden ? null : pickDrawing(drawings, at.cx, at.cy, projection);
          if (hit) {
            setChosen(hit.id);
            if (hit.kind === "fib") setSettingsFor(hit.id);
            return;
          }
          setZoom(1);
          setPriceView(null);
        }}
      >
        <svg
          ref={plot}
          width={plotRight + 8 + rightSpace}
          height={height}
          role="img"
          aria-label={`Futures price with flow nodes for ${frames.length} minutes. The table lists the selected minute.`}
        >
          {priceTicks.map((tick) => (
            <line
              key={tick}
              className="chart-grid"
              x1={MARGIN.left}
              x2={plotRight + rightSpace}
              y1={y(tick)}
              y2={y(tick)}
            />
          ))}
          {hourTicks.map((ns) => (
            <text key={ns} className="axis-tick" x={x(ns)} y={height - 8} textAnchor="middle">
              {nyHour(ns) === 0 ? formatDay(ns) : formatTime(ns)}
            </text>
          ))}
          {(showWalls || showFlip) && (
            <g className="flow-levels">
              {showWalls && <path className="flow-level-call" d={levelPath("call_wall")} />}
              {showWalls && <path className="flow-level-put" d={levelPath("put_wall")} />}
              {showFlip && <path className="flow-level-flip" d={levelPath("flip")} />}
            </g>
          )}
          {stripes.length > 0 && (
            <line className="flow-open" x1={x(open)} x2={x(open)} y1={MARGIN.top} y2={plotBottom} />
          )}
          <g className="flow-dots">
            {[...pastDots, ...stripes, ...dots].map((dot) => (
              <circle
                key={dot.key}
                className={[
                  dot.positive ? "flow-dot-positive" : "flow-dot-negative",
                  dot.king ? "flow-dot-king" : "",
                  showSecond && dot.second ? "flow-dot-second" : "",
                  "past" in dot ? "flow-dot-past" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                cx={x(dot.ns)}
                cy={y(dot.price)}
                r={0.8 + 2.6 * Math.sqrt(dot.share)}
                opacity={0.35 + 0.65 * dot.share}
              />
            ))}
          </g>
          <g className="candles" transform={candleTransform}>
            {settledCandles}
            {lastBar && candle(lastBar)}
          </g>
          {lastBar && (
            <line
              className="last-price-line"
              x1={MARGIN.left}
              x2={viewRight}
              y1={y(lastBar.close)}
              y2={y(lastBar.close)}
            />
          )}
          {!hidden && (
            <g className="drawings">
              {drawings.map((drawing) => (
                <g key={drawing.id}>{shape(drawing, drawing.id === chosen)}</g>
              ))}
            </g>
          )}
          {draft && <g className="drawings">{shape({ id: "draft", ...draft }, true)}</g>}
          {hover && !dragging && (
            <g className="crosshair">
              <line x1={hover.cx} x2={hover.cx} y1={MARGIN.top} y2={plotBottom} />
              <line x1={MARGIN.left} x2={viewRight} y1={y(priceAt(hover.cy))} y2={y(priceAt(hover.cy))} />
              <rect
                className="axis-badge"
                x={hover.cx - 34}
                y={plotBottom + 4}
                width={68}
                height={18}
                rx={3}
              />
              <text className="axis-badge-text" x={hover.cx} y={plotBottom + 17} textAnchor="middle">
                {formatTime(nsAt(hover.cx))}
              </text>
            </g>
          )}
          {selected === OVERNIGHT && stripes.length > 0 && (
            <g className="flow-cursor">
              <text
                x={(x(Math.max(start, overnight?.ts_ns ?? start)) + x(open)) / 2}
                y={MARGIN.top + 10}
                textAnchor="middle"
              >
                Overnight board
              </text>
            </g>
          )}
          {current && (
            <g className="flow-cursor">
              <line x1={x(current.ts_ns)} x2={x(current.ts_ns)} y1={MARGIN.top} y2={plotBottom} />
              <text x={x(current.ts_ns)} y={MARGIN.top + 10} textAnchor="middle">
                {formatTime(current.ts_ns)} · {formatPrice(current.spot * ratio)}
              </text>
            </g>
          )}
        </svg>
      </div>
      {/* The price axis stays put while the plot scrolls. */}
      {/* Drag the price axis to stretch or squeeze prices; double-click it to fit them again. */}
      <svg
        className="flow-axis"
        width={MARGIN.right}
        height={height}
        aria-hidden="true"
        onPointerDown={(event) => {
          axisDrag.current = { y: event.clientY, top, bottom };
          event.currentTarget.setPointerCapture?.(event.pointerId);
        }}
        onPointerMove={(event) => {
          const state = axisDrag.current;
          if (!state) return;
          const factor = Math.exp((event.clientY - state.y) * 0.006);
          const mid = (state.top + state.bottom) / 2;
          const half = ((state.top - state.bottom) / 2) * factor;
          setPriceView({ top: mid + half, bottom: mid - half });
        }}
        onPointerUp={() => {
          axisDrag.current = null;
        }}
        onDoubleClick={() => setPriceView(null)}
      >
        {priceTicks
          // A tick under the current-price or crosshair badge is hidden, so the badge reads cleanly.
          .filter(
            (tick) =>
              !hideTicksUnderTags ||
              [lastBar ? y(lastBar.close) : null, hover?.cy ?? null].every(
                (at) => at === null || Math.abs(y(tick) - at) > 14,
              ),
          )
          .map((tick) => (
            <text key={tick} className="axis-tick" x={6} y={y(tick) + 4}>
              {formatPrice(tick)}
            </text>
          ))}
        {!hidden &&
          drawings.map((drawing) =>
            drawing.kind === "hline" ? (
              <g key={drawing.id}>
                <rect
                  className="axis-badge axis-badge-drawing"
                  x={2}
                  y={y(drawing.price) - 9}
                  width={MARGIN.right - 4}
                  height={18}
                  rx={3}
                />
                <text className="axis-badge-text" x={6} y={y(drawing.price) + 4}>
                  {formatPrice(drawing.price)}
                </text>
              </g>
            ) : null,
          )}
        {lastBar && (
          <g>
            <rect
              className={
                lastBar.close >= lastBar.open
                  ? "axis-badge axis-badge-last up"
                  : "axis-badge axis-badge-last down"
              }
              x={2}
              y={y(lastBar.close) - 9}
              width={MARGIN.right - 4}
              height={18}
              rx={3}
            />
            <text className="axis-badge-text" x={6} y={y(lastBar.close) + 4}>
              {formatPrice(lastBar.close)}
            </text>
          </g>
        )}
        {hover && (
          <g>
            <rect
              className="axis-badge"
              x={2}
              y={y(priceAt(hover.cy)) - 9}
              width={MARGIN.right - 4}
              height={18}
              rx={3}
            />
            <text className="axis-badge-text" x={6} y={y(priceAt(hover.cy)) + 4}>
              {formatPrice(priceAt(hover.cy))}
            </text>
          </g>
        )}
      </svg>
      {chosenDrawing && !hidden && (
        <div className="drawing-bar" role="toolbar" aria-label="Selected drawing">
          {chosenFib && (
            <button
              type="button"
              className="draw-tool"
              aria-label="Drawing settings"
              title="Settings"
              aria-pressed={settingsFor === chosenFib.id}
              onClick={() => setSettingsFor((id) => (id === chosenFib.id ? null : chosenFib.id))}
            >
              <svg viewBox="0 0 20 20" aria-hidden="true">
                <path d="M3 6h8M15 6h2M3 14h2M9 14h8M13 4v4M7 12v4" />
              </svg>
            </button>
          )}
          <button
            type="button"
            className="draw-tool"
            aria-label="Delete drawing"
            title="Delete (Del)"
            onClick={() => {
              remove(chosenDrawing.id);
              setChosen(null);
            }}
          >
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path d="M4 6h12M8 6V4h4v2M6 6l1 10h6l1-10" />
            </svg>
          </button>
        </div>
      )}
      {chosenFib && settingsFor === chosenFib.id && !hidden && (
        <FibSettings
          key={chosenFib.id}
          style={chosenFib.fib ?? fibDefaults.defaults}
          onChange={(fib) => replace({ ...chosenFib, fib })}
          onSaveDefault={() => fibDefaults.save(chosenFib.fib ?? fibDefaults.defaults)}
          onClose={() => setSettingsFor(null)}
        />
      )}
      {legendBar && (
        <div className="chart-legend" aria-live="off">
          <span className="chart-legend-label">{label}</span>
          {(
            [
              ["O", legendBar.open],
              ["H", legendBar.high],
              ["L", legendBar.low],
              ["C", legendBar.close],
            ] as const
          ).map(([name, value]) => (
            <span key={name}>
              <span className="chart-legend-key">{name}</span> {formatPrice(value)}
            </span>
          ))}
          <span
            className={
              legendBar.close >= legendBar.open ? "chart-legend-change up" : "chart-legend-change down"
            }
          >
            {legendBar.close >= legendBar.open ? "+" : "−"}
            {formatPrice(Math.abs(legendBar.close - legendBar.open))} (
            {legendBar.close >= legendBar.open ? "+" : "−"}
            {((Math.abs(legendBar.close - legendBar.open) / legendBar.open) * 100).toFixed(2)}%)
          </span>
        </div>
      )}
      <span className="visually-hidden">
        {current && topNodes(current, 1)[0]
          ? `King node at ${formatTime(current.ts_ns)}: ${formatGex(topNodes(current, 1)[0]?.value ?? 0)}`
          : ""}
      </span>
    </div>
  );
}
