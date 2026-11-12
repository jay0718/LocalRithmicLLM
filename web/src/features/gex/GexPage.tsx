import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { PageHeader } from "../../components/PageHeader";
import { Select } from "../../components/ui/Select";
import { GexChart } from "./GexChart";
import { expiryOptions, formatExpiry } from "./expiries";
import { GexTable } from "./GexTable";
import { PriceChart, type CprMode, type ScaleMode } from "./PriceChart";
import { useCpr } from "./useCpr";
import { useEquityOverlay } from "./useEquityOverlay";
import { bucketOverlay, withOverlay, type OverlayMode } from "./overlay";
import { TIMEFRAMES, usePriceBars, type Timeframe } from "./usePriceBars";
import { makePriceScale } from "./scale";
import { useViewportHeight } from "../../lib/useViewportHeight";
import { useUnderlyings } from "./useUnderlyings";
import { formatGex, formatPrice, formatStrike } from "./format";
import {
  bucketChoices,
  defaultBucket,
  groupStrikes,
  nativeStep,
  strikesAround,
  withConvention,
  type Convention,
} from "./types";
import { useGexStream, type FeedStatus } from "./useGexStream";

const RANGE_KEY = "lrl.gex.range";
const SYMBOL_KEY = "lrl.gex.symbol";
const SCALE_KEY = "lrl.gex.priceScale";
const TIMEFRAME_KEY = "lrl.gex.timeframe";
const CPR_KEY = "lrl.gex.cpr";
const VALUES_KEY = "lrl.gex.values";
const OVERLAY_KEY = "lrl.gex.overlay";
/** Height of the panel controls above the plot, kept on screen with it. */
const CHART_CHROME = 150;
const MIN_CHART_HEIGHT = 420;
const EXPIRIES_KEY = "lrl.gex.expiries";
const DEFAULT_SYMBOL = "ESZ6";
const RANGES = [10, 20, 40];
const NO_ADVANCE_MS = 60_000;

const STATUS_TEXT: Record<FeedStatus, string> = {
  connecting: "Connecting",
  live: "Live",
  reconnecting: "Reconnecting",
  stale: "No updates",
};

const CONVENTIONS: { value: Convention; label: string }[] = [
  { value: "long_calls_short_puts", label: "Dealers long calls, short puts" },
  { value: "short_calls_long_puts", label: "Dealers short calls, long puts" },
];

function readRange(): number {
  try {
    const value = Number(localStorage.getItem(RANGE_KEY));
    return RANGES.includes(value) ? value : 20;
  } catch {
    return 20;
  }
}

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Remembering a choice is a convenience only.
  }
}

function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

function Stat({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "positive" | "negative";
}) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value num${tone ? ` stat-${tone}` : ""}`}>{value}</div>
      {detail && <div className="stat-detail">{detail}</div>}
    </div>
  );
}

export function GexPage() {
  const [params, setParams] = useSearchParams();
  const underlyings = useUnderlyings();
  const symbol = params.get("symbol") ?? readStored(SYMBOL_KEY) ?? DEFAULT_SYMBOL;
  const known = underlyings.data?.some((item) => item.symbol === symbol) ?? true;
  const product = underlyings.data?.find((item) => item.symbol === symbol);
  const available = product?.expiries ?? [];
  const [expiryChoice, setExpiryChoice] = useState<number | null>(
    () => Number(readStored(EXPIRIES_KEY)) || null,
  );
  // A remembered count larger than what this symbol has means "all of them".
  const expiries = expiryChoice && expiryChoice < available.length ? expiryChoice : null;
  const stream = useGexStream({ underlying: symbol, expiries });
  const { error: underlyingsError, reload: reloadUnderlyings } = underlyings;
  useEffect(() => {
    // The service may have been down when the page loaded; retry once it is reachable.
    if (stream.status === "live" && underlyingsError) void reloadUnderlyings();
  }, [stream.status, underlyingsError, reloadUnderlyings]);
  const [range, setRange] = useState(readRange);
  const [convention, setConvention] = useState<Convention>("long_calls_short_puts");
  const [showTable, setShowTable] = useState(false);
  const viewportHeight = useViewportHeight();
  const [showValues, setShowValues] = useState(() => readStored(VALUES_KEY) !== "off");
  const [timeframe, setTimeframe] = useState<Timeframe>(() => {
    const stored = readStored(TIMEFRAME_KEY);
    return TIMEFRAMES.some((item) => item.value === stored) ? (stored as Timeframe) : "1m";
  });
  const [cprMode, setCprMode] = useState<CprMode>(() => {
    const stored = readStored(CPR_KEY);
    return stored === "cpr" || stored === "pivots" ? stored : "off";
  });
  const priceBars = usePriceBars(symbol, timeframe, stream.liveBar, stream.connection);
  const cpr = useCpr(symbol);
  const etf = product?.overlay ?? null;
  const equity = useEquityOverlay(symbol, etf, expiries);
  const [overlayMode, setOverlayMode] = useState<OverlayMode>(() => {
    const stored = readStored(OVERLAY_KEY);
    return stored === "off" || stored === "combined" ? stored : "overlay";
  });
  const [scaleMode, setScaleMode] = useState<ScaleMode>(() =>
    readStored(SCALE_KEY) === "strikes" ? "strikes" : "fit",
  );
  const now = useNow();

  const snapshot = useMemo(
    () => (stream.snapshot ? withConvention(stream.snapshot, convention) : null),
    [stream.snapshot, convention],
  );
  const step = snapshot ? nativeStep(snapshot) : 1;
  const bucketKey = `lrl.gex.bucket.${symbol}`;
  const [bucketChoice, setBucketChoice] = useState<{ key: string; size: number | null }>(() => ({
    key: bucketKey,
    size: Number(readStored(bucketKey)) || null,
  }));
  if (bucketChoice.key !== bucketKey)
    setBucketChoice({ key: bucketKey, size: Number(readStored(bucketKey)) || null });
  const choices = bucketChoices(step);
  const bucket =
    bucketChoice.size && choices.includes(bucketChoice.size)
      ? bucketChoice.size
      : snapshot
        ? defaultBucket(step, snapshot.spot)
        : step;
  const grouped = snapshot ? groupStrikes(snapshot, bucket) : null;
  const overlayBuckets =
    etf && equity.overlay && overlayMode !== "off"
      ? bucketOverlay(equity.overlay, bucket, convention !== "long_calls_short_puts")
      : null;
  const combined = overlayMode === "combined" && overlayBuckets !== null;
  const profile = grouped && overlayBuckets ? withOverlay(grouped, overlayBuckets, combined) : grouped;
  // Headline levels follow what the profile shows: the future alone, or future plus ETF.
  const levels = combined ? profile : snapshot;
  const rows = profile ? strikesAround(profile, range) : [];
  // Fit the chart in the window below its own controls, so spot and live price stay on screen.
  const scale = makePriceScale(rows, Math.max(MIN_CHART_HEIGHT, viewportHeight - CHART_CHROME));

  function changeSymbol(value: string) {
    store(SYMBOL_KEY, value);
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set("symbol", value);
      return next;
    });
  }

  function changeRange(value: number) {
    setRange(value);
    store(RANGE_KEY, String(value));
  }

  const stale = stream.status === "stale" || stream.status === "reconnecting";
  const settlementDate = snapshot?.oldest_settlement
    ? `${snapshot.oldest_settlement.slice(0, 4)}-${snapshot.oldest_settlement.slice(4, 6)}-${snapshot.oldest_settlement.slice(6)}`
    : null;
  const marketQuiet =
    stream.marketOpen &&
    stream.status === "live" &&
    stream.lastAdvanceAt !== null &&
    now - stream.lastAdvanceAt > NO_ADVANCE_MS;
  const excluded = snapshot ? snapshot.contracts_total - snapshot.contracts_used : 0;
  const stalePercent =
    snapshot && snapshot.contracts_total ? (snapshot.stale_quotes / snapshot.contracts_total) * 100 : 0;
  const marketTime = snapshot ? new Date(snapshot.as_of_ns / 1e6) : null;

  return (
    <>
      <PageHeader
        title="GEX"
        description={`${product ? `${product.name} options` : "Futures options"} · dealer gamma per 1% move`}
        actions={
          <div className="gex-badges">
            {available.length > 1 && (
              <label className="symbol-picker">
                <span className="visually-hidden">Expiries</span>
                <Select
                  value={String(expiries ?? 0)}
                  onChange={(event) => {
                    const value = Number(event.target.value) || null;
                    setExpiryChoice(value);
                    store(EXPIRIES_KEY, String(value ?? 0));
                  }}
                  options={expiryOptions(available)}
                />
              </label>
            )}
            <label className="symbol-picker">
              <span className="visually-hidden">Symbol</span>
              <Select
                value={symbol}
                onChange={(event) => changeSymbol(event.target.value)}
                options={(underlyings.data ?? [{ symbol, product: "", name: symbol }]).map((item) => ({
                  value: item.symbol,
                  label: item.product ? `${item.product} · ${item.symbol}` : item.symbol,
                }))}
              />
            </label>
            {snapshot?.data_source === "synthetic" && (
              <span className="pill pill-warning">Synthetic data</span>
            )}
            {snapshot?.data_source === "rithmic" && <span className="pill pill-live">Rithmic</span>}
            <span className={`pill feed-${stream.status}`} role="status">
              <span className="feed-dot" aria-hidden="true" />
              {STATUS_TEXT[stream.status]}
            </span>
          </div>
        }
      />

      {!known && (
        <p className="banner banner-error" role="alert">
          {symbol} is not available. Choose a symbol from the list.
        </p>
      )}

      {!snapshot && known && (
        <div className="card empty">
          <h2>{stream.noData ? "Waiting for market data" : "Connecting to the GEX service"}</h2>
          <p className="muted">
            {stream.noData
              ? "The GEX service is running but has no prices yet. It publishes once the underlying futures have a quote."
              : "If this takes more than a few seconds, check that the GEX service is running."}
          </p>
        </div>
      )}

      {snapshot && (
        <>
          <div className="stats">
            <Stat label={`${snapshot.underlying} spot`} value={formatPrice(snapshot.spot)} />
            <Stat
              label={combined ? `Net GEX (${snapshot.underlying} + ${etf})` : "Net GEX"}
              value={formatGex((levels ?? snapshot).total_gex)}
              tone={(levels ?? snapshot).total_gex >= 0 ? "positive" : "negative"}
            />
            <Stat
              label={combined ? `Flip level (${snapshot.underlying} only)` : "Flip level"}
              value={snapshot.flip_level === null ? "None" : formatPrice(snapshot.flip_level)}
            />
            <Stat
              label="Call wall"
              value={
                (levels ?? snapshot).call_wall === null
                  ? "None"
                  : formatStrike((levels ?? snapshot).call_wall ?? 0)
              }
            />
            <Stat
              label="Put wall"
              value={
                (levels ?? snapshot).put_wall === null
                  ? "None"
                  : formatStrike((levels ?? snapshot).put_wall ?? 0)
              }
            />
            <Stat
              label="King node"
              value={
                (levels ?? snapshot).king_node === null
                  ? "None"
                  : formatStrike((levels ?? snapshot).king_node ?? 0)
              }
              {...((levels ?? snapshot).king_node_gex == null
                ? {}
                : { detail: `${formatGex((levels ?? snapshot).king_node_gex ?? 0)} net GEX` })}
            />
          </div>

          {stale && (
            <p className="banner" role="alert">
              {stream.status === "reconnecting"
                ? "Connection lost. Reconnecting… The chart shows the last snapshot received."
                : "No updates for over 5 seconds. The chart shows the last snapshot received."}
            </p>
          )}
          {!stream.marketOpen && (
            <p className="banner" role="status">
              Market closed (CME halts 5–6pm ET daily and over the weekend). Showing the last session&apos;s
              prices
              {snapshot.priced_from_settlement > 0
                ? ` with ${snapshot.priced_from_settlement} options priced from settlement${settlementDate ? `, the oldest from ${settlementDate}` : ""}.`
                : "."}
            </p>
          )}
          {marketQuiet && (
            <p className="banner">
              Market time hasn't moved for over a minute. The market may be closed or the feed may have
              stopped.
            </p>
          )}

          <div className="card gex-card">
            <div className="gex-toolbar">
              <div className="legend" aria-label="Legend">
                <span className="legend-item">
                  <span className="swatch swatch-positive" /> Positive
                </span>
                <span className="legend-item">
                  <span className="swatch swatch-negative" /> Negative
                </span>
                <span className="legend-item">
                  <span className="swatch-line swatch-spot" /> Spot
                </span>
                <span className="legend-item">
                  <span className="swatch-line swatch-flip" /> Flip
                </span>
                {overlayMode === "overlay" && overlayBuckets && (
                  <span className="legend-item">
                    <span className="swatch-overlay" /> {etf} (end of day)
                  </span>
                )}
              </div>
              <div className="gex-controls">
                {etf && (
                  <label>
                    <span className="visually-hidden">{etf} overlay</span>
                    <Select
                      value={overlayMode}
                      onChange={(event) => {
                        const mode = event.target.value as OverlayMode;
                        setOverlayMode(mode);
                        store(OVERLAY_KEY, mode);
                      }}
                      options={[
                        { value: "off", label: `${snapshot?.underlying ?? "Futures"} only` },
                        { value: "overlay", label: `+ ${etf} outline` },
                        { value: "combined", label: `+ ${etf} combined` },
                      ]}
                    />
                  </label>
                )}
                <label>
                  <span className="visually-hidden">Group strikes</span>
                  <Select
                    value={String(bucket)}
                    onChange={(event) => {
                      const size = Number(event.target.value);
                      setBucketChoice({ key: bucketKey, size });
                      store(bucketKey, String(size));
                    }}
                    options={choices.map((size) => ({
                      value: String(size),
                      label:
                        size === step
                          ? `Every strike (${formatStrike(size)})`
                          : `Per ${formatStrike(size)} points`,
                    }))}
                  />
                </label>
                <label>
                  <span className="visually-hidden">Rows shown</span>
                  <Select
                    value={String(range)}
                    onChange={(event) => changeRange(Number(event.target.value))}
                    options={RANGES.map((value) => ({ value: String(value), label: `±${value} rows` }))}
                  />
                </label>
                <label>
                  <span className="visually-hidden">Dealer positioning assumption</span>
                  <Select
                    value={convention}
                    onChange={(event) => setConvention(event.target.value as Convention)}
                    options={CONVENTIONS}
                  />
                </label>
                <button
                  type="button"
                  className="button button-ghost"
                  aria-pressed={showTable}
                  onClick={() => setShowTable((value) => !value)}
                >
                  {showTable ? "Chart" : "Table"}
                </button>
              </div>
            </div>

            <div className={stale ? "gex-plot is-stale" : "gex-plot"}>
              {rows.length === 0 || !scale ? (
                <p className="empty muted">No strikes have usable quotes and open interest yet.</p>
              ) : showTable ? (
                <GexTable rows={rows} />
              ) : (
                <div className="gex-panels">
                  <section aria-label="Price">
                    <div className="panel-header">
                      <h2 className="panel-title">{snapshot.underlying}</h2>
                      <div className="panel-controls">
                        <div className="segmented" role="group" aria-label="Timeframe">
                          {TIMEFRAMES.map((item) => (
                            <button
                              key={item.value}
                              type="button"
                              aria-pressed={timeframe === item.value}
                              onClick={() => {
                                setTimeframe(item.value);
                                store(TIMEFRAME_KEY, item.value);
                              }}
                            >
                              {item.label}
                            </button>
                          ))}
                        </div>
                        <div className="segmented" role="group" aria-label="Price scale">
                          {(["fit", "strikes"] as const).map((mode) => (
                            <button
                              key={mode}
                              type="button"
                              aria-pressed={scaleMode === mode}
                              onClick={() => {
                                setScaleMode(mode);
                                store(SCALE_KEY, mode);
                              }}
                            >
                              {mode === "fit" ? "Fit price" : "Match strikes"}
                            </button>
                          ))}
                        </div>
                        <label className="compact-select">
                          <span className="visually-hidden">Central pivot range</span>
                          <Select
                            value={cprMode}
                            onChange={(event) => {
                              const value = event.target.value as CprMode;
                              setCprMode(value);
                              store(CPR_KEY, value);
                            }}
                            options={[
                              { value: "off", label: "CPR off" },
                              { value: "cpr", label: "CPR" },
                              { value: "pivots", label: "CPR + R/S" },
                            ]}
                          />
                        </label>
                      </div>
                    </div>
                    {cprMode !== "off" && (
                      <p className="cpr-note muted">
                        {cpr
                          ? `CPR from the ${cpr.session_date} session: TC ${formatPrice(cpr.tc)}, pivot ${formatPrice(cpr.pivot)}, BC ${formatPrice(cpr.bc)}, width ${cpr.width_pct.toFixed(2)}%`
                          : "CPR needs a completed prior session."}
                      </p>
                    )}
                    {priceBars.error && <p className="cpr-note field-error">{priceBars.error}</p>}
                    <PriceChart
                      key={`${symbol}-${timeframe}`}
                      bars={priceBars.bars}
                      snapshot={levels ?? snapshot}
                      strikeScale={scale}
                      mode={scaleMode}
                      timeframe={timeframe}
                      cpr={cpr}
                      cprMode={cprMode}
                    />
                  </section>
                  <section aria-label="GEX by strike">
                    <div className="panel-header">
                      <h2 className="panel-title">
                        GEX {bucket === step ? "by strike" : `per ${formatStrike(bucket)} points`}
                      </h2>
                      <label className="checkbox">
                        <input
                          type="checkbox"
                          checked={showValues}
                          onChange={(event) => {
                            setShowValues(event.target.checked);
                            store(VALUES_KEY, event.target.checked ? "on" : "off");
                          }}
                        />
                        Values
                      </label>
                    </div>
                    {etf && overlayMode !== "off" && (
                      <p className="overlay-note">
                        {equity.overlay
                          ? `${etf} options expiring ${equity.overlay.expiries.map(formatExpiry).join(", ")}, from the ${formatExpiry(equity.overlay.trade_date)} close: $${equity.overlay.source_close.toFixed(2)} × ${equity.overlay.ratio.toFixed(2)} = ${formatPrice(equity.overlay.target_close)}${equity.overlay.ratio_basis === "live" ? " (live price)" : ""}. ${etf} net ${formatGex(equity.overlay.total_gex)}, king node ${equity.overlay.king_node === null ? "none" : formatPrice(equity.overlay.king_node)}. Open interest from OCC.${equity.overlay.prices_pending > 0 ? ` Still loading ${equity.overlay.prices_pending} of ${equity.overlay.series_total} strikes (free plan, 5 prices a minute); the nearest expiry loads first.` : ""}`
                          : equity.status === "building"
                            ? `${etf} end-of-day GEX is still being built; it appears here when ready.`
                            : `${etf} end-of-day GEX is unavailable.`}
                      </p>
                    )}
                    <GexChart
                      snapshot={profile ?? snapshot}
                      rows={rows}
                      scale={scale}
                      showValues={showValues}
                      {...(overlayMode === "overlay" && overlayBuckets
                        ? { overlay: overlayBuckets, overlayLabel: etf ?? "" }
                        : {})}
                    />
                  </section>
                </div>
              )}
            </div>

            <dl className="data-quality">
              <div>
                <dt>Market time</dt>
                <dd className="num">
                  {marketTime?.toLocaleString("en-US", {
                    month: "short",
                    day: "numeric",
                    hour: "numeric",
                    minute: "2-digit",
                    second: "2-digit",
                    timeZone: "America/New_York",
                    timeZoneName: "short",
                  })}
                </dd>
              </div>
              <div>
                <dt>Last update</dt>
                <dd className="num">
                  {stream.lastMessageAt === null
                    ? "—"
                    : `${Math.max(0, Math.round((now - stream.lastMessageAt) / 1000))}s ago`}
                </dd>
              </div>
              <div>
                <dt>Contracts used</dt>
                <dd className="num">
                  {snapshot.contracts_used.toLocaleString()} of {snapshot.contracts_total.toLocaleString()}
                </dd>
              </div>
              <div>
                <dt>Stale quotes</dt>
                <dd className="num">{stalePercent.toFixed(1)}%</dd>
              </div>
              <div>
                <dt>Excluded</dt>
                <dd
                  className="num"
                  title="Missing or stale quotes, missing open interest, or quotes that couldn't be priced"
                >
                  {excluded.toLocaleString()} ({snapshot.missing_open_interest} no OI, {snapshot.unpriced}{" "}
                  unpriced)
                </dd>
              </div>
              <div>
                <dt>Expiries</dt>
                <dd>{snapshot.expiries.length ? snapshot.expiries.map(formatExpiry).join(", ") : "—"}</dd>
              </div>
              <div>
                <dt>Assumption</dt>
                <dd>{CONVENTIONS.find((item) => item.value === convention)?.label}</dd>
              </div>
            </dl>
          </div>
        </>
      )}
    </>
  );
}
