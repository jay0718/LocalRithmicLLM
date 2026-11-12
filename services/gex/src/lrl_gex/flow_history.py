"""Minute-by-minute flow nodes for one option expiry, replayed from historical trades.

Each frame is the node map at that minute. How positions are priced into nodes is kept private;
this module holds the data model, the replay loop and storage.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from .flow import DEFAULT_RULES, FlowBook, FlowRules, OptionTrade

NY = ZoneInfo("America/New_York")
_NS = 1_000_000_000
_OSI = re.compile(r"^(?P<root>[A-Z]+)(?P<exp>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


@dataclass(frozen=True)
class FlowTrade:
    ts_ns: int
    symbol: str  # compact OSI, e.g. QQQ261110C00674000
    price: float
    size: int
    bid: float | None
    ask: float | None


@dataclass(frozen=True)
class OsiSymbol:
    root: str
    expiry: str  # YYYYMMDD
    is_call: bool
    strike: float


def parse_osi(symbol: str) -> OsiSymbol | None:
    match = _OSI.match(symbol.replace(" ", ""))
    if match is None:
        return None
    return OsiSymbol(match["root"], "20" + match["exp"], match["cp"] == "C", int(match["strike"]) / 1000)


class FlowNode(BaseModel):
    strike: float
    value: float  # dealer gamma, $ per $1 move


class NodeFrame(BaseModel):
    ts_ns: int
    spot: float
    nodes: list[FlowNode]
    # Levels in ETF prices: the strongest positive node (dealers long gamma, where rallies stall),
    # the strongest negative node, and the price where total dealer gamma changes sign.
    call_wall: float | None = None
    put_wall: float | None = None
    flip: float | None = None
    total: float = 0.0
    # Wall-clock time the frame was priced; with ts_ns (the last trade's exchange time) it gives
    # the feed and processing delay. Zero for frames built from history.
    computed_ns: int = 0


class FlowHistory(BaseModel):
    symbol: str
    expiry: str
    session_date: str  # YYYY-MM-DD
    frames: list[NodeFrame]
    # The board shown overnight before this session: this expiry's positions through the previous
    # session's close (4:15 PM, when the options stop trading), frozen until the open, since the
    # options do not trade overnight.
    overnight: NodeFrame | None = None


def session_bounds(day: date) -> tuple[int, int]:
    """Regular equity options session, 9:30 AM to 4:15 PM ET, in nanoseconds."""
    start = datetime(day.year, day.month, day.day, 9, 30, tzinfo=NY)
    end = datetime(day.year, day.month, day.day, 16, 15, tzinfo=NY)
    return int(start.timestamp()) * _NS, int(end.timestamp()) * _NS


class FlowState:
    """Positions, latest quotes and contract details for one expiry, priced into a node map on demand."""

    def __init__(self, expiry: str, strike_pct: float, rules: FlowRules = DEFAULT_RULES) -> None:
        self.book = FlowBook(inside_by_midpoint=not rules.skip_inside, skip_locked=rules.skip_locked)
        self.quotes: dict[str, tuple[float, float]] = {}
        self.contracts: dict[str, OsiSymbol] = {}
        self.strike_pct = strike_pct
        close = datetime(int(expiry[:4]), int(expiry[4:6]), int(expiry[6:]), 16, tzinfo=NY)
        self.expiry_ns = int(close.timestamp()) * _NS

    def apply(self, trade: FlowTrade) -> None:
        contract = self.contracts.get(trade.symbol) or parse_osi(trade.symbol)
        if contract is None:
            return
        self.contracts[trade.symbol] = contract
        self.book.apply(OptionTrade(trade.symbol, trade.price, trade.size, trade.bid, trade.ask))
        if trade.bid is not None and trade.ask is not None and trade.ask > 0 and trade.bid <= trade.ask:
            self.quotes[trade.symbol] = (trade.bid, trade.ask)

    def frame(self, ts_ns: int) -> NodeFrame | None:
        """Pricing positions into a node map is not part of the public repository; this build
        returns None, so no frames are produced."""
        return None


def build_history(
    trades: Iterable[FlowTrade],
    symbol: str,
    expiry: str,
    session: date,
    step_seconds: int = 60,
    strike_pct: float = 0.025,
    rules: FlowRules = DEFAULT_RULES,
) -> FlowHistory:
    """Frames every step through the session; trades must be in time order."""
    start_ns, end_ns = session_bounds(session)
    end_ns = min(end_ns, _expiry_cutoff(expiry))
    step_ns = step_seconds * _NS
    replay = FlowState(expiry, strike_pct, rules)
    frames: list[NodeFrame] = []
    overnight: NodeFrame | None = None
    last_prior_ns: int | None = None
    next_ns = start_ns + step_ns

    def emit_until(ts_ns: int) -> None:
        nonlocal next_ns
        while next_ns <= min(ts_ns, end_ns):
            if (frame := replay.frame(next_ns)) is not None:
                frames.append(frame)
            next_ns += step_ns

    opened = False

    def close_overnight() -> None:
        # Priced once, at the open, from the state the previous session ended with.
        nonlocal overnight, opened
        if not opened and last_prior_ns is not None:
            overnight = replay.frame(last_prior_ns)
        opened = True

    # The overnight board is the previous session's 4:15 PM close; prints after it (pre-market) wait.
    prior_close_ns = session_bounds(_previous_weekday(session))[1]
    for trade in trades:
        if trade.ts_ns > prior_close_ns:
            close_overnight()
        if trade.ts_ns >= start_ns:
            emit_until(trade.ts_ns)
        elif trade.ts_ns <= prior_close_ns:
            last_prior_ns = trade.ts_ns
        if trade.ts_ns > end_ns:
            break
        replay.apply(trade)
    close_overnight()
    emit_until(end_ns)
    return FlowHistory(
        symbol=symbol, expiry=expiry, session_date=session.isoformat(), frames=frames, overnight=overnight
    )


def _previous_weekday(day: date) -> date:
    previous = day - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous


def _expiry_cutoff(expiry: str) -> int:
    close = datetime(int(expiry[:4]), int(expiry[4:6]), int(expiry[6:]), 16, tzinfo=NY)
    return int(close.timestamp()) * _NS


class FlowStore:
    """Built histories as JSON files: <dir>/<SYMBOL>-<YYYYMMDD>.json with the default rules, and
    <dir>/<rules key>/<SYMBOL>-<YYYYMMDD>.json for the other filter settings."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, symbol: str, session_date: str, rules: FlowRules) -> Path:
        folder = self.directory / rules.key if rules.key else self.directory
        return folder / f"{symbol}-{session_date.replace('-', '')}.json"

    def save(self, history: FlowHistory, rules: FlowRules = DEFAULT_RULES) -> Path:
        path = self._path(history.symbol, history.session_date, rules)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(history.model_dump_json())
        return path

    def dates(self, symbol: str) -> list[str]:
        days = (p.stem.split("-", 1)[1] for p in self.directory.glob(f"{symbol}-[0-9]*.json"))
        return sorted(f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in days)

    def load(self, symbol: str, session_date: str, rules: FlowRules = DEFAULT_RULES) -> FlowHistory | None:
        path = self._path(symbol, session_date, rules)
        return FlowHistory.model_validate_json(path.read_text()) if path.exists() else None
