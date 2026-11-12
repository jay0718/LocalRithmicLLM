"""Live QQQ flow nodes from Databento's OPRA feed (needs a Databento live plan with OPRA.PILLAR).

The service runs one front expiry at a time:

1. Pick the expiry: today's 0DTE until the 4:15 PM ET close, then the next weekday's.
2. Subscribe to its calls and puts within a band around QQQ (``FLOW_LIVE_BAND``, default ±4%).
3. Rebuild positions from the day the expiry listed: the Historical API through last midnight
   (published in a daily batch, and cached on disk so a restart does not buy it again), then the
   Live API's intraday replay from midnight, so a start at any time of day has no gap.
4. Fold every trade in as it arrives and publish a node map each second. Each market minute keeps
   one frame; before the open, the frozen board from the previous close is shown.
5. At the close, save the session as a recorded day for the Flow page, and roll.

A dropped connection reconnects from the last trade it saw, and trades replayed twice across the
reconnect are dropped.

Configuration: ``FLOW_LIVE=databento`` with ``DATABENTO_API_KEY``. ``FLOW_LIVE=replay`` with
``FLOW_LIVE_FILES`` and ``FLOW_LIVE_SESSION`` runs the same service on recorded tcbbo files played
back at ``FLOW_LIVE_SPEED`` times market speed, for development without a live feed.
"""

import asyncio
import hashlib
import logging
import os
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from time import monotonic, time_ns
from typing import Protocol, TextIO

from .flow import ALL_RULES, DEFAULT_RULES, FlowRules
from .flow_dbn import osi_symbols
from .flow_history import NY, FlowHistory, FlowState, FlowStore, FlowTrade, NodeFrame, session_bounds
from .publisher import SnapshotHub

log = logging.getLogger(__name__)

TradeSource = AsyncIterator[FlowTrade]
_NS = 1_000_000_000
_MINUTE = 60 * _NS
# Streaming frames: one per 10 seconds of market time.
STREAM_STEP = 10 * _NS
DATASET = "OPRA.PILLAR"
SCHEMA = "tcbbo"
CLOSE = time(16, 15)  # QQQ options stop trading at 4:15 PM ET
LISTING_LOOKBACK = timedelta(days=35)
# NQ points per QQQ dollar is about 41; used only to centre the strike band when no QQQ price is known.
DEFAULT_NQ_PER_QQQ = 41.25


class _Variant:
    """The flow under one set of filter rules: its positions, frames and subscribers."""

    def __init__(self, expiry: str, strike_pct: float, rules: FlowRules) -> None:
        self.state = FlowState(expiry, strike_pct, rules)
        self.frames: list[NodeFrame] = []
        self.overnight: NodeFrame | None = None
        self.hub: SnapshotHub[NodeFrame] = SnapshotHub()
        # Streaming mode: one frame per STREAM_STEP (10 s) instead of per minute, each closed at its
        # last trade, so moves inside a minute stay visible after a reload.
        self.stream: list[NodeFrame] = []


def _put(frames: list[NodeFrame], frame: NodeFrame, step: int) -> None:
    """Replace the frame for the same ``step``-long bucket of market time, or add it."""
    if frames and frames[-1].ts_ns // step == frame.ts_ns // step:
        frames[-1] = frame
    elif not frames or frame.ts_ns > frames[-1].ts_ns:
        frames.append(frame)


class LiveFlow:
    """One expiry's live flow state and the frames published from it.

    Every combination of filter rules is kept side by side (folding a trade in costs about a
    microsecond, pricing a frame about 1.4 ms), so the page can switch filters without waiting
    for positions to be rebuilt. The default rules' variant is the one exposed as state, frames,
    overnight and hub.
    """

    def __init__(self, symbol: str, expiry: str, session: date, strike_pct: float = 0.025) -> None:
        self.symbol = symbol
        self.expiry = expiry
        self.session = session
        self.variants = {rules: _Variant(expiry, strike_pct, rules) for rules in ALL_RULES}
        self.market_ns = 0
        self.trades = 0
        self._open_ns, _ = session_bounds(session)

    def variant(self, rules: FlowRules = DEFAULT_RULES) -> _Variant:
        return self.variants[rules]

    @property
    def state(self) -> FlowState:
        return self.variant().state

    @property
    def frames(self) -> list[NodeFrame]:
        return self.variant().frames

    @property
    def overnight(self) -> NodeFrame | None:
        return self.variant().overnight

    @property
    def hub(self) -> SnapshotHub[NodeFrame]:
        return self.variant().hub

    def apply(self, trade: FlowTrade) -> None:
        if trade.ts_ns >= self._open_ns:
            self.freeze_overnight()
            # The first trade of a new 10-second bucket closes the previous one (and so every minute)
            # at its last trade, so frames are the same however fast trades arrive. A replay after a
            # restart folds in minutes at a time; the timer alone would keep arbitrary states.
            if self.market_ns >= self._open_ns and trade.ts_ns // STREAM_STEP > self.market_ns // STREAM_STEP:
                self.tick()
        for variant in self.variants.values():
            variant.state.apply(trade)
        self.market_ns = max(self.market_ns, trade.ts_ns)
        self.trades += 1

    def freeze_overnight(self) -> None:
        """Price the board as of the last trade before the open, once; it stays until the open."""
        if not self.market_ns or self.market_ns >= self._open_ns:
            return
        for variant in self.variants.values():
            if variant.overnight is None:
                variant.overnight = variant.state.frame(self.market_ns)
                if variant.overnight is not None:
                    variant.hub.publish(variant.overnight)

    def tick(self) -> NodeFrame | None:
        """Price the current node map; it replaces the frame for the same market minute (and the
        same 10 seconds in the streaming frames). Returns the default rules' frame."""
        if self.market_ns < self._open_ns:
            self.freeze_overnight()
            return None
        now = time_ns()
        published: NodeFrame | None = None
        for rules, variant in self.variants.items():
            frame = variant.state.frame(self.market_ns)
            if frame is None:
                continue
            frame = frame.model_copy(update={"computed_ns": now})
            _put(variant.frames, frame, _MINUTE)
            _put(variant.stream, frame, STREAM_STEP)
            variant.hub.publish(frame)
            if rules == DEFAULT_RULES:
                published = frame
        return published

    def history(self, rules: FlowRules = DEFAULT_RULES, stream: bool = False) -> FlowHistory:
        """The session so far: one frame per minute, or per 10 seconds with ``stream``."""
        variant = self.variant(rules)
        return FlowHistory(
            symbol=self.symbol,
            expiry=self.expiry,
            session_date=self.session.isoformat(),
            frames=list(variant.stream if stream else variant.frames),
            overnight=variant.overnight,
        )


def next_weekday(day: date) -> date:
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def front_session(now: datetime) -> date:
    """The session whose 0DTE expiry is the front one: today until the close, then the next weekday."""
    local = now.astimezone(NY)
    today = local.date()
    if today.weekday() < 5 and local.time() < CLOSE:
        return today
    return next_weekday(today)


def strike_band(center: float, pct: float) -> tuple[int, int]:
    return int(center * (1 - pct)), int(center * (1 + pct)) + 1


class Gateway(Protocol):
    """Where trades come from: published history up to a time, then a live stream from a time."""

    def history(self, symbols: list[str], start: datetime, end: datetime) -> Iterable[FlowTrade]: ...

    def stream(self, symbols: list[str], start: datetime) -> TradeSource: ...


class DatabentoGateway:
    """Databento Historical and Live clients for OPRA.PILLAR tcbbo (trades with the NBBO)."""

    def __init__(self, api_key: str, cache: Path | None = None, reconnect_delay: float = 2.0) -> None:
        self.api_key = api_key
        self.cache = cache
        self.reconnect_delay = reconnect_delay

    def history(self, symbols: list[str], start: datetime, end: datetime) -> Iterable[FlowTrade]:
        """Published trades in [start, end). Kept on disk per symbol set and end, so restarts
        during the day reuse what was already bought."""
        import databento as db

        from .flow_dbn import trades_from_store

        path = None
        if self.cache is not None:
            key = f"{symbols[0].replace(' ', '')}-{symbols[-1].replace(' ', '')}-{len(symbols)}"
            path = self.cache / f"{key}-{end.astimezone(UTC):%Y%m%dT%H%M}.dbn.zst"
            if path.exists():
                return trades_from_store(db.DBNStore.from_file(path))
            path.parent.mkdir(parents=True, exist_ok=True)
        client = db.Historical(self.api_key)
        store = client.timeseries.get_range(
            dataset=DATASET,
            schema=SCHEMA,
            stype_in="raw_symbol",
            symbols=symbols,
            start=start,
            end=end,
            path=str(path) if path else None,
        )
        return trades_from_store(store)

    async def stream(self, symbols: list[str], start: datetime) -> TradeSource:
        """Live trades from ``start`` (intraday replay), reconnecting from the last trade seen."""
        import databento as db

        resume = start
        last_ns = 0
        seen_at_last: set[tuple[int, int, int, int]] = set()
        while True:
            client = db.Live(key=self.api_key)
            names: dict[int, str] = {}
            try:
                client.subscribe(dataset=DATASET, schema=SCHEMA, stype_in="raw_symbol", symbols=symbols, start=resume)
                async for record in client:
                    if isinstance(record, db.SymbolMappingMsg):
                        names[record.instrument_id] = record.stype_out_symbol.replace(" ", "")
                        continue
                    if not isinstance(record, db.TCBBOMsg) or record.instrument_id not in names:
                        continue
                    # A reconnect replays from the last timestamp; skip trades already delivered.
                    key = (record.instrument_id, record.ts_event, record.price, record.size)
                    if record.ts_event < last_ns or (record.ts_event == last_ns and key in seen_at_last):
                        continue
                    if record.ts_event > last_ns:
                        last_ns, seen_at_last = record.ts_event, set()
                    seen_at_last.add(key)
                    yield FlowTrade(
                        ts_ns=record.ts_event,
                        symbol=names[record.instrument_id],
                        price=record.price / 1e9,
                        size=record.size,
                        bid=record.levels[0].bid_px / 1e9,
                        ask=record.levels[0].ask_px / 1e9,
                    )
                return
            except (db.BentoError, OSError, ConnectionError) as error:
                log.warning("Databento live stream dropped (%s); reconnecting", error)
                resume = datetime.fromtimestamp(last_ns / _NS, UTC) if last_ns else start
                await asyncio.sleep(self.reconnect_delay)
            finally:
                if hasattr(client, "terminate"):
                    client.terminate()


class ReplayGateway:
    """Recorded tcbbo trades through the same interface: history before a time is returned at
    once, and the stream plays the rest at its market-time spacing divided by ``speed``."""

    def __init__(
        self, trades: list[FlowTrade], speed: float = 60.0, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    ) -> None:
        self.trades = sorted(trades, key=lambda trade: trade.ts_ns)
        self.speed = speed
        self.sleep = sleep

    def _wanted(self, symbols: list[str]) -> set[str]:
        return {symbol.replace(" ", "") for symbol in symbols}

    def history(self, symbols: list[str], start: datetime, end: datetime) -> Iterable[FlowTrade]:
        wanted, lo, hi = self._wanted(symbols), start.timestamp() * _NS, end.timestamp() * _NS
        return [t for t in self.trades if t.symbol in wanted and lo <= t.ts_ns < hi]

    async def stream(self, symbols: list[str], start: datetime) -> TradeSource:
        wanted, lo = self._wanted(symbols), start.timestamp() * _NS
        previous: int | None = None
        for trade in self.trades:
            if trade.symbol not in wanted or trade.ts_ns < lo:
                continue
            if previous is not None and trade.ts_ns > previous:
                await self.sleep((trade.ts_ns - previous) / _NS / self.speed)
            previous = trade.ts_ns
            yield trade


async def run_live(
    flow: LiveFlow,
    source: TradeSource,
    min_interval: float = 0.05,
    heartbeat: float = 1.0,
    until_ns: int | None = None,
) -> None:
    """Fold trades into the flow and publish a fresh frame right after they arrive.

    A frame costs about 1.4 ms to price, so publishing follows the trades: the first trade after a
    quiet spell is priced at once, and a burst is coalesced to at most one frame per
    ``min_interval`` seconds. A ``heartbeat`` frame still goes out when nothing trades, so time
    decay keeps showing. Stops when the source ends or a trade reaches ``until_ns`` (the close).
    """
    loop = asyncio.get_running_loop()
    last = 0.0
    pending: asyncio.TimerHandle | None = None

    def publish() -> None:
        nonlocal last, pending
        pending = None
        last = loop.time()
        flow.tick()

    def soon() -> None:
        nonlocal pending
        if pending is None:
            pending = loop.call_later(max(0.0, min_interval - (loop.time() - last)), publish)

    async def heartbeats() -> None:
        while True:
            await asyncio.sleep(heartbeat)
            if loop.time() - last >= heartbeat:
                soon()

    beats = asyncio.create_task(heartbeats())
    try:
        async for trade in source:
            if until_ns is not None and trade.ts_ns >= until_ns:
                break
            flow.apply(trade)
            soon()
        if pending is not None:
            pending.cancel()
        flow.tick()
    finally:
        beats.cancel()
        if pending is not None:
            pending.cancel()


class TradeLog:
    """The session's streamed trades on disk, one CSV line each, so a restart reads them back in
    seconds instead of replaying the whole day from the feed (minutes). The first line names the
    contracts; a log for a different set is ignored. A line cut short by a crash is skipped."""

    def __init__(self, path: Path, symbols: list[str], flush_every: float = 1.0) -> None:
        self.path = path
        self.header = "# " + hashlib.sha1(",".join(sorted(symbols)).encode()).hexdigest()
        self.flush_every = flush_every
        self._file: TextIO | None = None
        self._flushed = 0.0

    def load(self) -> list[FlowTrade]:
        if not self.path.exists():
            return []
        lines = self.path.read_text().splitlines()
        if not lines or lines[0] != self.header:
            log.info("Trade log %s is for other contracts; starting a new one", self.path)
            self.path.unlink()
            return []
        trades = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) != 6:
                continue
            try:
                ts, symbol, price, size, bid, ask = parts
                trades.append(FlowTrade(int(ts), symbol, float(price), int(size), float(bid), float(ask)))
            except ValueError:
                continue
        return trades

    def append(self, trade: FlowTrade) -> None:
        if self._file is None:
            new = not self.path.exists()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open("a")
            if new:
                self._file.write(self.header + "\n")
        self._file.write(f"{trade.ts_ns},{trade.symbol},{trade.price!r},{trade.size},{trade.bid!r},{trade.ask!r}\n")
        now = monotonic()
        if now - self._flushed >= self.flush_every:
            self._file.flush()
            self._flushed = now

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


async def _resume(source: TradeSource, logged: list[FlowTrade], trade_log: TradeLog | None) -> TradeSource:
    """The stream from the last logged trade on: earlier trades and ones already logged at that
    same nanosecond are skipped; new ones are logged as they pass."""
    last = logged[-1].ts_ns if logged else 0
    pending = Counter(t for t in logged if t.ts_ns == last)
    async for trade in source:
        if trade.ts_ns < last:
            continue
        if trade.ts_ns == last and pending[trade] > 0:
            pending[trade] -= 1
            continue
        if trade_log is not None:
            trade_log.append(trade)
        yield trade


def _rebuild(
    flow: LiveFlow,
    gateway: Gateway,
    symbols: list[str],
    start: datetime,
    midnight: datetime,
    trade_log: TradeLog | None,
) -> tuple[int, list[FlowTrade]]:
    """Positions from the published history through midnight, then today's logged trades."""
    prior = _history(gateway, symbols, start, midnight)
    for trade in prior:
        flow.apply(trade)
    flow.freeze_overnight()
    logged = trade_log.load() if trade_log else []
    for trade in logged:
        flow.apply(trade)
    return len(prior), logged


def _history(gateway: Gateway, symbols: list[str], start: datetime, end: datetime) -> list[FlowTrade]:
    return list(gateway.history(symbols, start, end))


@dataclass
class LiveSettings:
    root: str = "QQQ"
    band: float = 0.04
    min_interval: float = 0.05
    # Where each session's streamed trades are kept for fast restarts; None keeps nothing.
    log_dir: Path | None = None


async def run_flow_service(
    gateway: Gateway,
    attach: Callable[[LiveFlow], None],
    store: FlowStore,
    center: Callable[[], float | None],
    settings: LiveSettings | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sessions: int | None = None,
) -> None:
    """Run the front expiry live, save it at the close, roll, and repeat (``sessions`` limits it)."""
    settings = settings or LiveSettings()
    done = 0
    while sessions is None or done < sessions:
        session = front_session(now())
        expiry = session.strftime("%Y%m%d")
        mid = center()
        if mid is None:
            log.warning("No %s price yet to centre the strike band; waiting", settings.root)
            await asyncio.sleep(10)
            continue
        symbols = osi_symbols(settings.root, expiry, *strike_band(mid, settings.band))
        flow = LiveFlow(settings.root, expiry, session)
        attach(flow)
        # Positions since listing: published history through last midnight, then today's trades:
        # read back from the trade log when this session ran before, then the live feed from there.
        midnight = datetime.combine(min(now().astimezone(NY).date(), session), time(0), NY)
        open_ = datetime.combine(session, time(9, 30), NY)
        trade_log = (
            TradeLog(settings.log_dir / f"{settings.root}-{expiry}-trades.csv", symbols) if settings.log_dir else None
        )

        started = monotonic()
        # In a worker thread: hundreds of thousands of trades would stall the event loop.
        prior_count, logged = await asyncio.to_thread(
            _rebuild, flow, gateway, symbols, open_ - LISTING_LOOKBACK, midnight, trade_log
        )
        log.info(
            "Flow %s %s: %d contracts, %d earlier trades, %d from today's log, rebuilt in %.1fs",
            settings.root,
            expiry,
            len(symbols),
            prior_count,
            len(logged),
            monotonic() - started,
        )
        resume = datetime.fromtimestamp(logged[-1].ts_ns / _NS, UTC) if logged else midnight
        _, close_ns = session_bounds(session)
        try:
            source = _resume(gateway.stream(symbols, resume), logged, trade_log)
            await run_live(flow, source, settings.min_interval, until_ns=close_ns)
        finally:
            if trade_log is not None:
                trade_log.close()
        if flow.frames:
            for rules in ALL_RULES:
                store.save(flow.history(rules), rules)
            log.info("Saved flow session %s", session)
        done += 1


def flow_service_from_env(
    center: Callable[[], float | None],
) -> Callable[[Callable[[LiveFlow], None]], Awaitable[None]] | None:
    """The configured live flow service, ready to attach to a runtime, or None when FLOW_LIVE is off."""
    mode = os.environ.get("FLOW_LIVE", "")
    store = FlowStore(Path(os.environ.get("FLOW_DIR", "data/flow")))
    settings = LiveSettings(
        root=os.environ.get("FLOW_LIVE_ROOT", "QQQ"),
        band=float(os.environ.get("FLOW_LIVE_BAND", "0.04")),
        min_interval=float(os.environ.get("FLOW_LIVE_MIN_INTERVAL_MS", "50")) / 1000,
    )
    if mode == "databento":
        cache = Path(os.environ.get("FLOW_LIVE_CACHE", "data/flow-raw/live-cache"))
        gateway: Gateway = DatabentoGateway(os.environ["DATABENTO_API_KEY"], cache=cache)
        settings.log_dir = cache
        return lambda attach: run_flow_service(gateway, attach, store, center, settings)
    if mode == "replay":
        from .flow_dbn import read_trades

        trades = list(read_trades([Path(f) for f in os.environ["FLOW_LIVE_FILES"].split(",")]))
        gateway = ReplayGateway(trades, speed=float(os.environ.get("FLOW_LIVE_SPEED", "60")))
        # A recorded day runs as if it were that morning, before the open.
        session = date.fromisoformat(os.environ["FLOW_LIVE_SESSION"])
        morning = datetime.combine(session, time(9, 0), NY)
        return lambda attach: run_flow_service(
            gateway, attach, store, center, settings, now=lambda: morning, sessions=1
        )
    return None
