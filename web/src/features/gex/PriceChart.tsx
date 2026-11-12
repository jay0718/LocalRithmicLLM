import { useEffect, useRef, useState, type PointerEvent } from "react";
import { useElementWidth } from "../../lib/useElementWidth";
import { formatPrice } from "./format";
import { makeFitScale, niceTicks, spreadLabels, type PriceScale } from "./scale";
import type { Bar, GexSnapshot } from "./types";
import type { Cpr } from "./useCpr";
import type { Timeframe } from "./usePriceBars";
import { breaksBefore } from "./breaks";
import { DEFAULT_SLOT, INITIAL_VIEW, distance, maxOffsetFor, zoomAround, type Viewport } from "./viewport";

const PRICE_AXIS = 80;
const MARGIN = { left: 8, right: 8 + PRICE_AXIS };
const ZOOM_SPEED = 0.0025;

function manualScale(
  top: number,
  bottom: number,
  height: number,
  plotTop: number,
  plotBottom: number,
): PriceScale {
  const plotHeight = height - plotTop - plotBottom;
  return {
    top,
    bottom,
    step: 0,
    row: 0,
    height,
    y: (price) => plotTop + ((top - price) / (top - bottom)) * plotHeight,
    contains: (price) => price <= top && price >= bottom,
  };
}
const TIME_TICKS = 4;

export type ScaleMode = "strikes" | "fit";
export type CprMode = "off" | "cpr" | "pivots";

type Level = { key: string; label: string; price: number | null; className: string };

const intraday = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "America/New_York",
});
const dayTime = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  timeZone: "America/New_York",
});
const dayOnly = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "America/New_York",
});

function formatBarTime(startNs: number, timeframe: Timeframe): string {
  const date = new Date(startNs / 1e6);
  if (timeframe === "1d") {
    // A CME session opens at 6pm the evening before the date it is named for.
    return dayOnly.format(new Date(startNs / 1e6 + 6 * 3600_000));
  }
  return timeframe === "1h" ? dayTime.format(date) : intraday.format(date);
}

/**
 * Candles for the chosen timeframe with GEX levels and an optional CPR overlay.
 * Drag or scroll sideways to move back through history.
 */
export function PriceChart({
  bars,
  snapshot,
  strikeScale,
  mode,
  timeframe,
  cpr,
  cprMode,
}: {
  bars: Bar[];
  snapshot: GexSnapshot;
  strikeScale: PriceScale;
  mode: ScaleMode;
  timeframe: Timeframe;
  cpr: Cpr | null;
  cprMode: CprMode;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const [view, setView] = useState<Viewport>(INITIAL_VIEW);
  const drag = useRef<{
    x: number;
    y: number;
    view: Viewport;
    axis: boolean;
    top: number;
    bottom: number;
  } | null>(null);
  const pinch = useRef<{ distance: number; view: Viewport } | null>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const [dragging, setDragging] = useState(false);

  const plotWidth = Math.max(width - MARGIN.left - MARGIN.right, 0);
  const slot = view.slot;
  const candle = Math.max(1, Math.round(slot * 0.7));
  const capacityAt = (size: number) => Math.max(Math.floor(plotWidth / size), 1);
  const capacity = capacityAt(slot);
  const maxOffset = maxOffsetFor(bars.length, capacity);
  const offset = Math.min(view.offset, maxOffset);
  const whole = Math.floor(offset);
  const shift = (offset - whole) * slot;
  const end = bars.length - whole;
  const shown = bars.slice(Math.max(end - capacity - 1, 0), end);
  const xFor = (index: number) =>
    MARGIN.left + plotWidth - (shown.length - index) * slot + shift + (slot - candle) / 2;

  const showCpr = cprMode !== "off" && cpr !== null;
  const manual =
    mode === "fit" && view.range
      ? manualScale(view.range.top, view.range.bottom, strikeScale.height, 28, 8)
      : null;
  const fitted =
    mode === "fit" && !manual
      ? makeFitScale(
          shown.map((bar) => bar.low),
          shown.map((bar) => bar.high),
          strikeScale.height,
          Math.max(strikeScale.step / 5, 1),
        )
      : null;
  const scale = manual ?? fitted ?? strikeScale;
  const clampY = (price: number) => Math.min(Math.max(scale.y(price), 0), scale.height);
  const priceTicks = mode === "fit" ? niceTicks(scale.bottom, scale.top) : [];

  const levels: Level[] = [
    { key: "king", label: "King node", price: snapshot.king_node, className: "level-king" },
    { key: "call", label: "Call wall", price: snapshot.call_wall, className: "level-call" },
    { key: "put", label: "Put wall", price: snapshot.put_wall, className: "level-put" },
    { key: "flip", label: "Flip", price: snapshot.flip_level, className: "level-flip" },
    { key: "spot", label: "Spot", price: snapshot.spot, className: "level-spot" },
  ];
  if (showCpr && cpr) {
    levels.push({ key: "pivot", label: "Pivot", price: cpr.pivot, className: "level-cpr" });
    if (cprMode === "pivots") {
      for (const [key, label] of [
        ["r2", "R2"],
        ["r1", "R1"],
        ["s1", "S1"],
        ["s2", "S2"],
      ] as const) {
        levels.push({ key, label, price: cpr[key], className: "level-pivot" });
      }
    }
  }

  const visibleLevels = levels.filter(
    (level): level is Level & { price: number } => level.price !== null && scale.contains(level.price),
  );
  const labelYs = spreadLabels(visibleLevels.map((level) => scale.y(level.price) - 4));
  const tagYs = spreadLabels(
    visibleLevels.map((level) => scale.y(level.price)),
    17,
  );
  const axisX = width - MARGIN.right + 8;
  const offLevels = levels.filter((level) => level.price !== null && !scale.contains(level.price));
  const offScale =
    mode === "strikes" && shown.some((bar) => !scale.contains(bar.high) || !scale.contains(bar.low));
  const hovered = hover === null ? undefined : shown[hover];
  const timeTicks =
    shown.length > 1
      ? Array.from({ length: TIME_TICKS }, (_, i) => Math.round((i * (shown.length - 1)) / (TIME_TICKS - 1)))
      : [0];

  // Wheel and trackpad: scroll sideways to pan, scroll or pinch to zoom around the cursor.
  // A native listener is needed because React's wheel handler cannot prevent page scroll.
  const latest = useRef({ view, plotWidth, total: bars.length, capacityAt });
  useEffect(() => {
    latest.current = { view, plotWidth, total: bars.length, capacityAt };
  });
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    function onWheel(event: WheelEvent) {
      event.preventDefault();
      const { view, plotWidth, total, capacityAt } = latest.current;
      const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
      if (Math.abs(event.deltaX) > Math.abs(event.deltaY) && !event.ctrlKey) {
        const offset = Math.min(
          Math.max(view.offset + event.deltaX / view.slot, 0),
          maxOffsetFor(total, capacityAt(view.slot)),
        );
        setView({ ...view, offset });
        return;
      }
      const fromRight = Math.max(MARGIN.left + plotWidth - (event.clientX - rect.left), 0);
      const factor = Math.exp(-event.deltaY * ZOOM_SPEED * (event.ctrlKey ? 4 : 1));
      setView(zoomAround(view, factor, fromRight, total, capacityAt));
    }
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, [ref]);

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const spread = distance(pointers.current.values());
    if (spread) {
      pinch.current = { distance: spread, view };
      drag.current = null;
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      view: { ...view, offset },
      axis: event.clientX - rect.left > width - MARGIN.right,
      top: scale.top,
      bottom: scale.bottom,
    };
    setDragging(true);
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (pointers.current.has(event.pointerId))
      pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const spread = distance(pointers.current.values());
    if (pinch.current && spread) {
      setView(
        zoomAround(
          pinch.current.view,
          spread / pinch.current.distance,
          plotWidth / 2,
          bars.length,
          capacityAt,
        ),
      );
      return;
    }
    const start = drag.current;
    if (!start) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    const span = start.top - start.bottom;
    const plotHeight = Math.max(scale.height - 36, 1);
    if (start.axis && mode === "fit") {
      // Drag the price axis to stretch or squeeze prices around the middle.
      const factor = Math.exp(dy * 0.01);
      const middle = (start.top + start.bottom) / 2;
      setView({
        ...start.view,
        range: { top: middle + (span / 2) * factor, bottom: middle - (span / 2) * factor },
      });
      return;
    }
    const offsetNow = Math.min(Math.max(start.view.offset + dx / start.view.slot, 0), maxOffset);
    const moved = mode === "fit" && (start.view.range !== null || Math.abs(dy) > 6);
    const priceShift = (dy / plotHeight) * span;
    setView({
      ...start.view,
      offset: offsetNow,
      range: moved ? { top: start.top + priceShift, bottom: start.bottom + priceShift } : start.view.range,
    });
  }

  function endDrag(event: PointerEvent<HTMLDivElement>) {
    pointers.current.delete(event.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
    drag.current = null;
    setDragging(false);
  }

  const cprTop = showCpr && cpr ? clampY(cpr.tc) : 0;
  const cprBottom = showCpr && cpr ? clampY(cpr.bc) : 0;

  return (
    <div
      className="price-chart"
      ref={ref}
      onMouseLeave={() => setHover(null)}
      onDoubleClick={() => setView(INITIAL_VIEW)}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      data-dragging={dragging}
    >
      <svg
        width={width}
        height={scale.height}
        role="img"
        aria-label={`${snapshot.underlying} ${timeframe} price chart with ${shown.length} candles and GEX levels`}
      >
        <defs>
          <clipPath id="price-plot">
            <rect x={0} y={0} width={width} height={scale.height} />
          </clipPath>
        </defs>

        {shown.length > 0 &&
          timeTicks.map((index, position) => {
            const bar = shown[index];
            if (!bar) return null;
            const anchor = position === 0 ? "start" : position === timeTicks.length - 1 ? "end" : "middle";
            const x =
              position === 0
                ? MARGIN.left
                : position === timeTicks.length - 1
                  ? width - MARGIN.right
                  : xFor(index);
            return (
              <text
                key={`${bar.start_ns}-${position}`}
                className="chart-tick"
                x={x}
                y={16}
                textAnchor={anchor}
              >
                {formatBarTime(bar.start_ns, timeframe)}
              </text>
            );
          })}

        {priceTicks.map((tick) => (
          <line
            key={tick}
            className="chart-grid"
            x1={0}
            x2={width - MARGIN.right + 8}
            y1={scale.y(tick)}
            y2={scale.y(tick)}
          />
        ))}

        {showCpr && cpr && cprBottom > cprTop && (
          <rect
            className="cpr-band"
            x={0}
            width={width}
            y={cprTop}
            height={Math.max(cprBottom - cprTop, 1)}
          />
        )}

        {visibleLevels.map((level) => (
          <line
            key={level.key}
            className={`price-level-line ${level.className}`}
            x1={0}
            x2={axisX}
            y1={scale.y(level.price)}
            y2={scale.y(level.price)}
          />
        ))}

        {breaksBefore(shown, timeframe).map(({ index, session }) => (
          <line
            key={`break-${shown[index]?.start_ns}`}
            className={session ? "session-break" : "gap-break"}
            x1={xFor(index) - (slot - candle) / 2}
            x2={xFor(index) - (slot - candle) / 2}
            y1={24}
            y2={scale.height}
          />
        ))}

        <g clipPath="url(#price-plot)">
          {shown.map((bar, index) => {
            const x = xFor(index);
            const up = bar.close >= bar.open;
            const bodyTop = clampY(Math.max(bar.open, bar.close));
            const bodyHeight = Math.max(clampY(Math.min(bar.open, bar.close)) - bodyTop, 1);
            return (
              <g
                key={bar.start_ns}
                className={up ? "candle candle-up" : "candle candle-down"}
                onMouseEnter={() => setHover(index)}
                onTouchStart={() => setHover(index)}
              >
                <rect
                  className="candle-hit"
                  x={x - (slot - candle) / 2}
                  y={0}
                  width={slot}
                  height={scale.height}
                />
                <line x1={x + candle / 2} x2={x + candle / 2} y1={clampY(bar.high)} y2={clampY(bar.low)} />
                <rect
                  x={x + 0.5}
                  y={bodyTop}
                  width={Math.max(candle - 1, 1)}
                  height={bodyHeight}
                  rx={candle > 4 ? 1 : 0}
                />
              </g>
            );
          })}
        </g>

        {visibleLevels.map((level, index) => (
          <text
            key={level.key}
            className={`price-level-label ${level.className}`}
            x={axisX - 6}
            y={labelYs[index]}
            textAnchor="end"
          >
            {level.label}
          </text>
        ))}

        {/* The price axis: tick labels, then a tag for each level on top. */}
        <rect className="price-axis" x={axisX} y={0} width={PRICE_AXIS} height={scale.height} />
        {priceTicks.map((tick) => (
          <text key={tick} className="axis-tick" x={axisX + 6} y={scale.y(tick) + 4}>
            {formatPrice(tick)}
          </text>
        ))}
        {visibleLevels.map((level, index) => (
          <g key={level.key} className={`axis-tag ${level.className}`}>
            <rect x={axisX + 1} y={(tagYs[index] ?? 0) - 8} width={PRICE_AXIS - 2} height={16} rx={3} />
            <text x={axisX + 6} y={(tagYs[index] ?? 0) + 4}>
              {formatPrice(level.price)}
            </text>
          </g>
        ))}

        {hovered && hover !== null && (
          <line
            className="crosshair"
            x1={xFor(hover) + candle / 2}
            x2={xFor(hover) + candle / 2}
            y1={24}
            y2={scale.height}
          />
        )}
      </svg>

      {shown.length === 0 && <p className="price-empty muted">No price bars yet.</p>}
      {offLevels.length > 0 && (
        <ul className="off-levels" aria-label="Levels outside this view">
          {offLevels.map((level) => (
            <li key={level.key} className={level.className}>
              {(level.price ?? 0) > scale.top ? "↑" : "↓"} {level.label} {formatPrice(level.price ?? 0)}
            </li>
          ))}
        </ul>
      )}
      {offScale && (
        <p className="price-note muted">Some prices are outside the strikes shown. Widen the strike range.</p>
      )}
      {(offset > 0.5 || view.range !== null || view.slot !== DEFAULT_SLOT) && (
        <button
          type="button"
          className="button button-small button-secondary latest-button"
          onClick={() => setView(INITIAL_VIEW)}
        >
          Reset view
        </button>
      )}

      {hovered && hover !== null && (
        <div
          className="chart-tooltip"
          role="tooltip"
          style={{
            top: Math.min(scale.y(hovered.close), scale.height - 70),
            left: Math.min(xFor(hover) + 14, Math.max(width - 170, 0)),
          }}
        >
          <strong>{formatBarTime(hovered.start_ns, timeframe)}</strong>
          <dl>
            <dt>Open</dt>
            <dd>{formatPrice(hovered.open)}</dd>
            <dt>High</dt>
            <dd>{formatPrice(hovered.high)}</dd>
            <dt>Low</dt>
            <dd>{formatPrice(hovered.low)}</dd>
            <dt>Close</dt>
            <dd>{formatPrice(hovered.close)}</dd>
            <dt>Volume</dt>
            <dd>{hovered.volume.toLocaleString()}</dd>
          </dl>
        </div>
      )}
    </div>
  );
}
