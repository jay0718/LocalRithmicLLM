"""OHLC bars: building them from events, aggregating timeframes, and CME trading days."""

from collections import deque
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from .events import OpenInterest, Quote, Trade

NEW_YORK = ZoneInfo("America/New_York")
Interval = Literal["1m", "5m", "15m", "1h", "1d"]
INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}

MINUTE_NS = 60 * 1_000_000_000


class Bar(BaseModel):
    start_ns: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    trades: int


class BarBuilder:
    """Trades set the bar's prices. A minute with no trades is drawn from quote mids instead,
    so quiet markets still show price movement.
    """

    def __init__(self, symbol: str, interval_ns: int = MINUTE_NS, max_bars: int = 20_000) -> None:
        self.symbol = symbol
        self._interval = interval_ns
        self._closed: deque[Bar] = deque(maxlen=max_bars)
        self.current: Bar | None = None
        self.out_of_order = 0
        # Events at or before the end of seeded history are already counted in it.
        self._seeded_until_ns = -1
        self.session_hours_only = True

    def apply(self, event: Trade | Quote | OpenInterest) -> None:
        if event.symbol != self.symbol:
            return
        if isinstance(event, Trade):
            self._update(event.exchange_ts_ns, event.price, event.size, is_trade=True)
        elif isinstance(event, Quote) and event.bid_price is not None and event.ask_price is not None:
            self._update(event.exchange_ts_ns, (event.bid_price + event.ask_price) / 2, 0, is_trade=False)

    def _update(self, ts_ns: int, price: float, size: int, is_trade: bool) -> None:
        if ts_ns <= self._seeded_until_ns:
            return
        if self.session_hours_only and not is_session_minute(datetime.fromtimestamp(ts_ns / 1e9, UTC)):
            # Quotes keep arriving during the daily halt and weekends; they are not trading.
            return
        start = ts_ns - ts_ns % self._interval
        bar = self.current
        if bar is not None and start < bar.start_ns:
            self.out_of_order += 1
            return
        if bar is None or start > bar.start_ns:
            if bar is not None:
                self._closed.append(bar)
            self.current = Bar(
                start_ns=start,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=size,
                trades=int(is_trade),
            )
            return
        if is_trade and bar.trades == 0:
            # The first trade replaces prices drawn from quotes.
            bar.open = bar.high = bar.low = bar.close = price
        elif not is_trade and bar.trades > 0:
            return
        bar.high = max(bar.high, price)
        bar.low = min(bar.low, price)
        bar.close = price
        bar.volume += size
        bar.trades += int(is_trade)

    def seed(self, history: Iterable[Bar]) -> None:
        """Load closed bars from history, before any live events."""
        for bar in history:
            self._closed.append(bar.model_copy())
            # Rithmic's bars include trades stamped exactly at their end, so the boundary is inclusive.
            self._seeded_until_ns = max(self._seeded_until_ns, bar.start_ns + self._interval)

    def backfill(self, history: Iterable[Bar]) -> int:
        """Merge finished bars fetched after a gap (e.g. a reconnect): missing minutes are added and
        ones already held are replaced by the exchange's complete version. The forming bar is left
        alone. Returns how many minutes were new."""
        current = self.current.start_ns if self.current else None
        held = {bar.start_ns: bar for bar in self._closed}
        added = 0
        for bar in history:
            if current is not None and bar.start_ns >= current:
                continue
            added += bar.start_ns not in held
            held[bar.start_ns] = bar.model_copy()
        if added or held:
            self._closed = deque(sorted(held.values(), key=lambda bar: bar.start_ns), maxlen=self._closed.maxlen)
        return added

    @property
    def last_closed(self) -> Bar | None:
        """The most recently finished bar."""
        return self._closed[-1] if self._closed else None

    def all_bars(self) -> list[Bar]:
        return [*self._closed, *([self.current] if self.current else [])]

    def bars(self, limit: int) -> list[Bar]:
        """The most recent bars, oldest first, including the one still forming."""
        all_bars = [*self._closed, *([self.current] if self.current else [])]
        return [bar.model_copy() for bar in all_bars[-limit:]] if limit > 0 else []


def trading_date(start_ns: int) -> date:
    """The CME trading day a minute belongs to. Sessions run 6pm to 5pm New York time,
    so anything from 6pm on belongs to the next calendar day."""
    local = datetime.fromtimestamp(start_ns / 1e9, UTC).astimezone(NEW_YORK)
    return (local + timedelta(hours=6)).date()


def session_open_ns(day: date) -> int:
    opened = datetime(day.year, day.month, day.day, 18, tzinfo=NEW_YORK) - timedelta(days=1)
    return int(opened.timestamp() * 1e9)


def _combine(start_ns: int, group: Sequence[Bar]) -> Bar:
    return Bar(
        start_ns=start_ns,
        open=group[0].open,
        high=max(bar.high for bar in group),
        low=min(bar.low for bar in group),
        close=group[-1].close,
        volume=sum(bar.volume for bar in group),
        trades=sum(bar.trades for bar in group),
    )


def aggregate(bars: Sequence[Bar], interval: Interval) -> list[Bar]:
    """Combine 1-minute bars, in time order, into the given timeframe."""
    if interval == "1m":
        return [bar.model_copy() for bar in bars]
    if interval == "1d":
        key = lambda bar: session_open_ns(trading_date(bar.start_ns))  # noqa: E731
    else:
        size = INTERVAL_MINUTES[interval] * MINUTE_NS
        key = lambda bar: bar.start_ns - bar.start_ns % size  # noqa: E731
    result: list[Bar] = []
    group: list[Bar] = []
    current = None
    for bar in bars:
        bucket = key(bar)
        if group and bucket != current:
            result.append(_combine(current, group))
            group = []
        current = bucket
        group.append(bar)
    if group:
        result.append(_combine(current, group))
    return result


def is_session_minute(start: datetime) -> bool:
    """CME equity index futures trade Sunday 6pm to Friday 5pm New York time, halting 5pm to 6pm daily."""
    local = start.astimezone(NEW_YORK)
    weekday, hour = local.weekday(), local.hour
    if hour == 17 or weekday == 5:
        return False
    if weekday == 4 and hour >= 18:
        return False
    return not (weekday == 6 and hour < 18)
