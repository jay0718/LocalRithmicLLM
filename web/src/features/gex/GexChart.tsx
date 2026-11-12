import { useState } from "react";
import { useElementWidth } from "../../lib/useElementWidth";
import { formatGex, formatPrice, formatStrike, symmetricTicks } from "./format";
import { SCALE_BOTTOM, SCALE_TOP, spreadLabels, type PriceScale } from "./scale";
import type { GexSnapshot, StrikeGex } from "./types";

const MAX_BAR = 12;
/** Vertical room a strike or value label needs so neighbours don't overlap. */
const LABEL_PX = 12;
const RADIUS = 4;
const MARGIN = { top: SCALE_TOP, right: 132, bottom: SCALE_BOTTOM, left: 64 };
const LABEL_CLEARANCE = 14;

/** A bar with a rounded data end and a square end on the zero baseline. */
function barPath(zero: number, end: number, top: number, BAR: number): string {
  const width = Math.abs(end - zero);
  if (width < 0.5) return "";
  const r = Math.min(RADIUS, width, BAR / 2);
  const dir = end > zero ? 1 : -1;
  const bottom = top + BAR;
  return [
    `M${zero},${top}`,
    `H${end - dir * r}`,
    `Q${end},${top} ${end},${top + r}`,
    `V${bottom - r}`,
    `Q${end},${bottom} ${end - dir * r},${bottom}`,
    `H${zero}`,
    "Z",
  ].join(" ");
}

type Hover = { row: StrikeGex; y: number } | null;

const INSIDE_MIN_PX = 58;

/**
 * A node's net GEX at the end of its bar: inside long bars, just past the tip of short ones.
 * Values are compact ($850K, $42.6M, $1.2B).
 */
function NodeValue({ value, zero, tip, y }: { value: number; zero: number; tip: number; y: number }) {
  const positive = value >= 0;
  const inside = Math.abs(tip - zero) >= INSIDE_MIN_PX;
  const xText = inside ? tip + (positive ? -5 : 5) : tip + (positive ? 5 : -5);
  const anchor = positive === inside ? "end" : "start";
  return (
    <text
      className={inside ? "node-value node-value-inside" : "node-value"}
      x={xText}
      y={y}
      textAnchor={anchor}
      dominantBaseline="central"
    >
      {formatGex(value, 1)}
    </text>
  );
}

export function GexChart({
  snapshot,
  rows,
  scale,
  showValues = true,
  overlay,
  overlayLabel = "",
}: {
  snapshot: GexSnapshot;
  rows: StrikeGex[];
  scale: PriceScale;
  showValues?: boolean;
  /** A second profile drawn as outlined bars on the same rows and axis, keyed by row strike. */
  overlay?: Map<number, StrikeGex>;
  overlayLabel?: string;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<Hover>(null);
  // Skip values for nodes under 2% of the largest, which would only add clutter near zero.
  const labelFloor = Math.max(...rows.map((row) => Math.abs(row.net_gex)), 0) * 0.02;
  const ROW = scale.row;
  const BAR = Math.max(2, Math.min(MAX_BAR, ROW - 3));
  // When rows are tight, label every nth strike, always including the walls and king node.
  const strikeEvery = Math.ceil(LABEL_PX / ROW);
  const walls = [snapshot.call_wall, snapshot.put_wall, snapshot.king_node].filter(
    (strike): strike is number => strike != null,
  );
  const rowIndex = (strike: number) => Math.round((scale.top - strike) / scale.step);
  const showStrike = (strike: number) =>
    walls.includes(strike) ||
    (rowIndex(strike) % strikeEvery === 0 &&
      walls.every((wall) => Math.abs(rowIndex(wall) - rowIndex(strike)) >= strikeEvery));
  // Value labels go to the largest nodes first, skipping any that would overlap one already placed.
  const valued = new Set<number>();
  const placed: number[] = [];
  for (const row of [...rows].sort((a, b) => Math.abs(b.net_gex) - Math.abs(a.net_gex))) {
    if (Math.abs(row.net_gex) < labelFloor) break;
    const y = scale.y(row.strike);
    if (placed.every((other) => Math.abs(other - y) >= LABEL_PX - 1)) {
      placed.push(y);
      valued.add(row.strike);
    }
  }

  const height = scale.height;
  const plotLeft = MARGIN.left;
  const plotRight = Math.max(width - MARGIN.right, plotLeft + 80);
  const overlayRows = overlay
    ? rows.map((row) => overlay.get(row.strike)).filter((row) => row !== undefined)
    : [];
  const { limit, ticks } = symmetricTicks(
    Math.max(
      ...rows.map((row) => Math.abs(row.net_gex)),
      ...overlayRows.map((row) => Math.abs(row.net_gex)),
      0,
    ),
  );
  const zero = (plotLeft + plotRight) / 2;
  const x = (value: number) => zero + (value / limit) * ((plotRight - plotLeft) / 2);
  const rowCenter = (row: StrikeGex) => scale.y(row.strike);
  const yForPrice = (price: number) => (scale.contains(price) ? scale.y(price) : null);

  const spotY = yForPrice(snapshot.spot);
  const flipY = snapshot.flip_level === null ? null : yForPrice(snapshot.flip_level);
  const [spotLabelY, flipLabelY] =
    spotY !== null && flipY !== null ? spreadLabels([spotY, flipY], 14) : [spotY, flipY];
  const showTicks = width >= 420 ? ticks : ticks.filter((_, index) => index % 2 === 0);

  return (
    <div className="gex-chart" ref={ref}>
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`Net GEX for ${rows.length} rows around spot ${formatPrice(snapshot.spot)}. Use the table view for exact values.`}
      >
        {showTicks.map((tick) => (
          <g key={tick}>
            <line
              className={tick === 0 ? "chart-baseline" : "chart-grid"}
              x1={x(tick)}
              x2={x(tick)}
              y1={MARGIN.top - 6}
              y2={height - MARGIN.bottom}
            />
            <text className="chart-tick" x={x(tick)} y={MARGIN.top - 12} textAnchor="middle">
              {tick === 0 ? "0" : formatGex(tick, 1)}
            </text>
          </g>
        ))}

        {rows.map((row) => {
          const isWall =
            row.strike === snapshot.call_wall ||
            row.strike === snapshot.put_wall ||
            row.strike === snapshot.king_node;
          const crowded = [spotY, flipY].some(
            (y) => y !== null && Math.abs(y - rowCenter(row)) < LABEL_CLEARANCE,
          );
          const isKing = row.strike === snapshot.king_node;
          const wallLabel = crowded
            ? null
            : isKing
              ? "King node"
              : row.strike === snapshot.call_wall && row.strike === snapshot.put_wall
                ? "Call & put wall"
                : row.strike === snapshot.call_wall
                  ? "Call wall"
                  : row.strike === snapshot.put_wall
                    ? "Put wall"
                    : null;
          return (
            <g
              key={row.strike}
              className="chart-row"
              data-active={hover?.row.strike === row.strike}
              onMouseEnter={() => setHover({ row, y: rowCenter(row) })}
              onMouseLeave={() => setHover(null)}
              onTouchStart={() => setHover({ row, y: rowCenter(row) })}
            >
              <rect className="chart-hit" x={0} y={rowCenter(row) - ROW / 2} width={width} height={ROW} />
              {showStrike(row.strike) && (
                <text
                  className={isWall ? "chart-strike chart-strike-wall" : "chart-strike"}
                  x={plotLeft - 10}
                  y={rowCenter(row)}
                  textAnchor="end"
                  dominantBaseline="central"
                >
                  {formatStrike(row.strike)}
                </text>
              )}
              <path
                className={row.net_gex >= 0 ? "bar-positive" : "bar-negative"}
                d={barPath(zero, x(row.net_gex), rowCenter(row) - BAR / 2, BAR)}
              />
              {overlay?.get(row.strike) && (
                <path
                  className="bar-overlay"
                  d={barPath(zero, x(overlay.get(row.strike)?.net_gex ?? 0), rowCenter(row) - BAR / 2, BAR)}
                />
              )}
              {showValues && valued.has(row.strike) && (
                <NodeValue value={row.net_gex} zero={zero} tip={x(row.net_gex)} y={rowCenter(row)} />
              )}
              {wallLabel && (
                <text
                  className="chart-annotation"
                  x={plotRight + 10}
                  y={rowCenter(row)}
                  dominantBaseline="central"
                >
                  {wallLabel}
                </text>
              )}
            </g>
          );
        })}

        {flipY !== null && (
          <g className="chart-flip">
            <line x1={plotLeft} x2={plotRight} y1={flipY} y2={flipY} />
            <text x={plotRight + 10} y={flipLabelY ?? flipY} dominantBaseline="central">
              Flip {formatPrice(snapshot.flip_level ?? 0)}
            </text>
          </g>
        )}
        {spotY !== null && (
          <g className="chart-spot">
            <line x1={plotLeft} x2={plotRight} y1={spotY} y2={spotY} />
            <circle cx={plotLeft} cy={spotY} r={4} />
            <text x={plotRight + 10} y={spotLabelY ?? spotY} dominantBaseline="central">
              Spot {formatPrice(snapshot.spot)}
            </text>
          </g>
        )}
      </svg>

      {hover && (
        <div
          className="chart-tooltip"
          role="tooltip"
          style={{
            top: hover.y,
            left: hover.row.net_gex >= 0 ? plotLeft + 8 : Math.max(zero + 12, plotLeft + 8),
          }}
        >
          <strong>Strike {formatStrike(hover.row.strike)}</strong>
          <dl>
            <dt>Net GEX</dt>
            <dd>{formatGex(hover.row.net_gex)}</dd>
            <dt>Calls</dt>
            <dd>{formatGex(hover.row.call_gex)}</dd>
            <dt>Puts</dt>
            <dd>{formatGex(hover.row.put_gex)}</dd>
            {overlay && (
              <>
                <dt>{overlayLabel}</dt>
                <dd>{formatGex(overlay.get(hover.row.strike)?.net_gex ?? 0)}</dd>
              </>
            )}
          </dl>
        </div>
      )}
    </div>
  );
}
