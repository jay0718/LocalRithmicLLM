"""Per-underlying state: the option chain, its bars and the hub that publishes updates."""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from lrl_common.bars import Bar, BarBuilder, is_session_minute
from lrl_common.contracts import OptionContract
from lrl_common.events import OpenInterest, Quote, Settlement, Trade
from pydantic import BaseModel

from .chain import ChainState
from .engine import EngineConfig, GexSnapshot, compute_snapshot
from .equity_eod import EquityEod
from .flow_live import LiveFlow
from .publisher import SnapshotHub


@dataclass(frozen=True)
class Product:
    code: str
    symbol: str
    name: str
    multiplier: float


PRODUCTS = {
    "ES": Product("ES", "ESZ6", "E-mini S&P 500", 50.0),
    "NQ": Product("NQ", "NQZ6", "E-mini Nasdaq-100", 20.0),
    "RTY": Product("RTY", "RTYZ6", "E-mini Russell 2000", 50.0),
    "YM": Product("YM", "YMZ6", "E-mini Dow", 5.0),
}


class LiveUpdate(BaseModel):
    """What subscribers receive each tick: the latest GEX snapshot and the forming bar."""

    underlying: str
    snapshot: GexSnapshot | None
    bar: Bar | None
    market_open: bool = True


class BarTick(BaseModel):
    """The forming bar, sent as soon as a trade changes it, with the bar that finished before it.

    Subscribers keep only the newest message, so the finished bar rides along on every one: a
    viewer that missed the last update of a minute still gets that minute's final shape.
    """

    bar: Bar
    previous: Bar | None = None


class UnderlyingRuntime:
    def __init__(self, product: Product, contracts: Iterable[OptionContract], config: EngineConfig) -> None:
        self.product = product
        self.chain = ChainState(product.symbol, contracts)
        self.bars = BarBuilder(product.symbol)
        self.config = config
        # One hub per expiry count requested by viewers; None means every tracked expiry.
        self.hubs: dict[int | None, SnapshotHub[LiveUpdate]] = {None: SnapshotHub()}
        self.follow_market_hours = False
        # End-of-day GEX for the ETF overlaid on this future (e.g. QQQ on NQ), when configured.
        self.equity_symbol: str | None = None
        self.equity: EquityEod | None = None
        # Live ETF flow nodes on this future, when FLOW_LIVE is set.
        self.flow_live: LiveFlow | None = None
        # The forming bar on its own, sent per change rather than once per GEX computation.
        self.bar_hub: SnapshotHub[BarTick] = SnapshotHub()

    @property
    def hub(self) -> SnapshotHub[LiveUpdate]:
        return self.hubs[None]

    def hub_for(self, expiries: int | None) -> SnapshotHub[LiveUpdate]:
        if expiries not in self.hubs:
            self.hubs[expiries] = SnapshotHub()
        return self.hubs[expiries]

    def upcoming_expiries(self) -> list[str]:
        return sorted({c.expiry for c in self.chain.contracts.values() if c.expiry_ts_ns > self.chain.now_ns})

    def compute_all(self, now: datetime | None = None) -> dict[int | None, LiveUpdate]:
        """An update for every requested expiry count, computed from the same moment."""
        results = {}
        for expiries in list(self.hubs):
            update = self.compute(now, expiries)
            if update is not None:
                results[expiries] = update
        return results

    def publish(self, updates: dict[int | None, LiveUpdate]) -> None:
        for expiries, update in updates.items():
            self.hubs[expiries].publish(update)

    def apply(self, event: Trade | Quote | OpenInterest | Settlement) -> None:
        self.chain.apply(event)
        if event.symbol != self.product.symbol:
            return
        before = self.bars.current
        before_state = before.model_dump() if before is not None else None
        self.bars.apply(event)
        current = self.bars.current
        # Only changes are sent: most quotes leave a bar with trades untouched.
        if current is not None and current.model_dump() != before_state:
            self.bar_hub.publish(BarTick(bar=current.model_copy(), previous=self.bars.last_closed))

    def compute(self, now: datetime | None = None, expiries: int | None = None) -> LiveUpdate | None:
        market_open = True
        config = replace(self.config, max_expiries=expiries)
        if self.follow_market_hours:
            market_open = is_session_minute(now or datetime.now(UTC))
            # Live options are often quoted on one side only; their settlement is the best price then.
            config = replace(config, settlement_fallback=True)
            if not market_open:
                # While the market is shut, the last session's quotes are the best available,
                # so they are used rather than excluded as stale.
                config = replace(config, stale_after_seconds=7 * 86_400, settlement_fallback=True)
        snapshot = compute_snapshot(self.chain, config)
        bar = self.bars.current.model_copy() if self.bars.current else None
        if snapshot is None and bar is None:
            return None
        return LiveUpdate(underlying=self.product.symbol, snapshot=snapshot, bar=bar, market_open=market_open)
