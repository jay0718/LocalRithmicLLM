import { useMemo, useState } from "react";
import { useStoredState } from "../../lib/useStoredState";
import { PageHeader } from "../../components/PageHeader";
import { Select } from "../../components/ui/Select";
import { useViewportHeight } from "../../lib/useViewportHeight";
import { formatExpiry } from "../gex/expiries";
import { formatPrice } from "../gex/format";
import { FilterMenu } from "./FilterMenu";
import { FlowGuide } from "./FlowGuide";
import { useLiveBar, withLiveBar } from "./useLiveBar";
import { FlowChart, OVERNIGHT } from "./FlowChart";
import { FlowLevels } from "./FlowLevels";
import { NodeCheatSheet } from "./NodeCheatSheet";
import { NodeTable } from "./NodeTable";
import {
  formatDay,
  formatTime,
  sessionRatio,
  useFlowDates,
  useFlowLive,
  useFlowLiveAvailable,
  useFlowSession,
  usePastSessions,
  STREAM_STEP_NS,
} from "./useFlowHistory";

const UNDERLYING = "NQZ6";
const ETF = "QQQ";
const COUNTS = [0, 8, 12, 20, 30];
const LIVE = "live";

/** The polled bars with the stream's forming candle in place of (or after) the last one. */
/** With nodes hidden on the chart, the table still lists this many for reference. */
const TABLE_WHEN_HIDDEN = 12;
const MINUTE = 60_000_000_000;
type ChartWindow = "session" | "premarket" | "overnight";
/** Candle intervals in minutes; one-minute bars are combined only when a longer one is picked. */
const INTERVALS = [1, 2, 3, 5, 10, 15, 30, 60];
const intervalLabel = (minutes: number) => (minutes % 60 === 0 ? `${minutes / 60}h` : `${minutes}m`);
const WINDOWS: { value: ChartWindow; label: string }[] = [
  { value: "premarket", label: "From 6:00 AM" },
  { value: "overnight", label: "From previous close" },
  { value: "session", label: "Session only" },
];

export function FlowPage() {
  const dates = useFlowDates(UNDERLYING);
  const liveAvailable = useFlowLiveAvailable(UNDERLYING);
  const [chosen, setChosen] = useState<string | null>(null);
  const date = chosen ?? (liveAvailable ? LIVE : (dates.data?.at(-1) ?? null));
  const isLive = date === LIVE;
  // Trade filters (each combination is computed on the server) and a display option, remembered.
  const [skipInside, setSkipInside] = useStoredState("lrl.flow.skipInside", true);
  const [skipLocked, setSkipLocked] = useStoredState("lrl.flow.skipLocked", true);
  const [hideTicks, setHideTicks] = useStoredState("lrl.flow.hideTicksUnderTags", true);
  const [showSecond, setShowSecond] = useStoredState("lrl.flow.showSecond", true);
  // The guide opens on a first visit; closing it is remembered.
  const [showGuide, setShowGuide] = useStoredState("lrl.flow.showGuide", true);
  const filters = useMemo(() => ({ skipInside, skipLocked }), [skipInside, skipLocked]);
  const recorded = useFlowSession(UNDERLYING, isLive ? null : date, filters);
  // Per minute, or Streaming: a node map every 10 seconds, so moves inside a minute show.
  const [mode, setMode] = useStoredState<string>("lrl.flow.mode", "minute");
  const streaming = mode === "stream";
  const live = useFlowLive(UNDERLYING, isLive, undefined, filters, streaming);
  // The week before this session, from the saved sessions, drawn when zoomed out.
  const sessionDate = isLive ? (live.data?.history.session_date ?? null) : date;
  const past = usePastSessions(UNDERLYING, dates.data ?? null, sessionDate, filters);
  const session = isLive ? live : recorded;
  // View choices are remembered in this browser; the session always opens on the latest.
  const [count, setCount] = useStoredState("lrl.flow.count", 12);
  const [interval, setCandleInterval] = useStoredState("lrl.flow.interval", 1);
  const [selected, setSelected] = useState<number | null>(null);
  const [chartWindow, setChartWindow] = useStoredState<ChartWindow>("lrl.flow.window", "premarket");
  // Off until turned on.
  const [showWalls, setShowWalls] = useStoredState("lrl.flow.showWalls", false);
  const [showFlip, setShowFlip] = useStoredState("lrl.flow.showFlip", false);
  const viewportHeight = useViewportHeight();

  const history = session.data?.history;
  // Live: the forming NQ candle, sent by the server as soon as a trade changes it.
  const liveBar = useLiveBar(UNDERLYING, isLive);
  const loadedBars = session.data?.bars;
  const bars = useMemo(
    () => (isLive ? withLiveBar(loadedBars ?? [], liveBar) : (loadedBars ?? [])),
    [isLive, loadedBars, liveBar],
  );
  const ratio = history ? sessionRatio(history, bars) : null;
  const frames = history?.frames ?? [];
  const newest = frames.at(-1);
  // Exchange time of the last trade to the moment its node map was priced (feed + processing).
  const latency =
    isLive && newest?.computed_ns ? Math.max(0, Math.round((newest.computed_ns - newest.ts_ns) / 1e6)) : null;
  const overnight = history?.overnight ?? null;
  const overnightRatio = history?.overnight_ratio ?? ratio;
  const index = selected === null ? frames.length - 1 : Math.min(selected, frames.length - 1);
  const showingOvernight = index === OVERNIGHT && overnight !== null;
  const frame = showingOvernight ? overnight : frames[index];
  const open = (frames[0]?.ts_ns ?? 0) - MINUTE;
  const windowStart =
    chartWindow === "overnight" && overnight
      ? overnight.ts_ns
      : chartWindow === "premarket"
        ? open - (3 * 60 + 30) * MINUTE
        : open;

  return (
    <>
      <PageHeader
        title="Flow nodes"
        description={`${ETF} 0DTE dealer gamma, on NQ · per $1 move`}
        actions={
          <button
            type="button"
            className="filter-button"
            aria-expanded={showGuide}
            onClick={() => setShowGuide(!showGuide)}
          >
            How to read
          </button>
        }
      />
      {showGuide && <FlowGuide onClose={() => setShowGuide(false)} />}
      <div className="flow-toolbar">
        <label>
          <span className="visually-hidden">Session</span>
          <Select
            value={date ?? ""}
            onChange={(event) => {
              setChosen(event.target.value);
              setSelected(null);
            }}
            options={[
              ...(liveAvailable ? [{ value: LIVE, label: "Live" }] : []),
              ...(dates.data ?? []).map((value) => ({ value, label: value })),
            ]}
            disabled={!dates.data?.length && !liveAvailable}
          />
        </label>
        {isLive && (
          <label>
            <span className="visually-hidden">Mode</span>
            <Select
              value={streaming ? "stream" : "minute"}
              onChange={(event) => setMode(event.target.value)}
              options={[
                { value: "minute", label: "Per minute" },
                { value: "stream", label: "Streaming (10 s)" },
              ]}
            />
          </label>
        )}
        <label>
          <span className="visually-hidden">Candle interval</span>
          <Select
            value={String(interval)}
            onChange={(event) => setCandleInterval(Number(event.target.value))}
            options={INTERVALS.map((minutes) => ({ value: String(minutes), label: intervalLabel(minutes) }))}
          />
        </label>
        <label>
          <span className="visually-hidden">Chart window</span>
          <Select
            value={chartWindow}
            onChange={(event) => setChartWindow(event.target.value as ChartWindow)}
            options={WINDOWS}
          />
        </label>
        <label>
          <span className="visually-hidden">Nodes shown</span>
          <Select
            value={String(count)}
            onChange={(event) => setCount(Number(event.target.value))}
            options={COUNTS.map((value) => ({
              value: String(value),
              label: value === 0 ? "No nodes (levels only)" : `Top ${value} nodes`,
            }))}
          />
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={showWalls}
            onChange={(event) => setShowWalls(event.target.checked)}
          />
          Walls
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={showFlip} onChange={(event) => setShowFlip(event.target.checked)} />
          Flip
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={showSecond}
            onChange={(event) => setShowSecond(event.target.checked)}
          />
          2nd node
        </label>
        <FilterMenu
          options={[
            {
              key: "inside",
              label: "Skip trades inside the spread",
              hint: "Trades between the bid and the ask are not counted. Off: they go to the nearer side.",
              checked: skipInside,
              initial: true,
              onChange: setSkipInside,
            },
            {
              key: "locked",
              label: "Skip locked or crossed quotes",
              hint: "Trades while the bid is at or above the ask are not counted. Off: signed like any other.",
              checked: skipLocked,
              initial: true,
              onChange: setSkipLocked,
            },
            {
              key: "ticks",
              label: "Hide axis prices under price tags",
              hint: "Axis prices behind the current-price and crosshair tags are hidden.",
              checked: hideTicks,
              initial: true,
              onChange: setHideTicks,
            },
          ]}
        />
        <span className="flow-hint">Drag to scroll · wheel to zoom · double-click to fit</span>
        {isLive && history && (
          <span className="pill feed-live" title="Time from the last trade at the exchange to its node map">
            <span className="feed-dot" />
            Live{latency !== null ? ` · ${latency} ms` : ""}
          </span>
        )}
        {history && ratio && (
          <span className="flow-meta">
            Expiry {formatExpiry(history.expiry)} · {ETF} × {ratio.toFixed(3)} = NQ
            {frame && !showingOvernight
              ? ` · ${formatTime(frame.ts_ns)} ET, ${ETF} ${formatPrice(frame.spot)}`
              : ""}
          </span>
        )}
      </div>

      {dates.status === "ready" && !dates.data?.length && !liveAvailable && (
        <p className="empty">No flow sessions yet. Build one with lrl_gex.flow_dbn from Databento trades.</p>
      )}
      {(dates.status === "error" || session.status === "error") && (
        <p className="field-error">Couldn't load the flow history.</p>
      )}

      {history && ratio && frame && (
        <div className="card flow-card">
          <FlowChart
            bars={bars}
            frames={frames}
            ratio={ratio}
            overnight={overnight}
            overnightRatio={overnightRatio}
            windowStart={windowStart}
            follow={isLive}
            showWalls={showWalls}
            showFlip={showFlip}
            count={count}
            selected={index}
            onSelect={setSelected}
            height={Math.max(420, viewportHeight - 260)}
            storageKey={`lrl.flow.drawings.${UNDERLYING}`}
            label={`${UNDERLYING} · ${intervalLabel(interval)}`}
            interval={interval}
            hideTicksUnderTags={hideTicks}
            frameStep={isLive && streaming ? STREAM_STEP_NS : MINUTE}
            showSecond={showSecond}
            past={past}
            viewKey={`lrl.flow.view.${UNDERLYING}.${isLive ? "live" : date}`}
          />
          <section aria-label={`Nodes at ${formatTime(frame.ts_ns)}`} className="flow-side">
            <h2 className="panel-title">
              {showingOvernight
                ? `Overnight board, from the ${formatDay(frame.ts_ns)} close`
                : `${formatTime(frame.ts_ns)} ET`}
            </h2>
            <FlowLevels
              frame={frame}
              ratio={showingOvernight ? (overnightRatio ?? ratio) : ratio}
              etf={ETF}
            />
            <NodeTable
              frame={frame}
              ratio={showingOvernight ? (overnightRatio ?? ratio) : ratio}
              count={count || TABLE_WHEN_HIDDEN}
              etf={ETF}
            />
            <NodeCheatSheet />
          </section>
        </div>
      )}
    </>
  );
}
