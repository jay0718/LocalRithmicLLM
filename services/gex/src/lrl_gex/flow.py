"""Dealer option positions from trade flow. The signing rules are kept private; this module
defines the data types and the bookkeeping around them.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class FlowRules:
    """Trade filter settings, selectable on the page."""

    skip_inside: bool = True
    skip_locked: bool = True

    @property
    def key(self) -> str:
        """A short name for files and logs: "" for the defaults."""
        parts = [] if self.skip_inside else ["inside"]
        parts += [] if self.skip_locked else ["locked"]
        return "+".join(parts)


DEFAULT_RULES = FlowRules()
# Every combination, so the page can switch between them without recomputing anything.
ALL_RULES = [FlowRules(inside, locked) for inside in (True, False) for locked in (True, False)]


class Side(Enum):
    BUY = 1  # customer bought, dealer sold
    SELL = -1  # customer sold, dealer bought
    UNKNOWN = 0


@dataclass(frozen=True)
class OptionTrade:
    symbol: str
    price: float
    size: int
    bid: float | None
    ask: float | None


def classify(
    price: float,
    bid: float | None,
    ask: float | None,
    last_price: float | None = None,
    inside_by_midpoint: bool = False,
    skip_locked: bool = True,
) -> Side:
    """How trades are signed is not part of the public repository; this build signs none."""
    return Side.UNKNOWN


class FlowBook:
    """Net customer contracts per option, accumulated over every session since the contract listed.

    Summing across sessions matters: a contract's earlier sessions often decide which side
    dealers are on at a strike, which a single day's flow cannot show.
    """

    def __init__(self, inside_by_midpoint: bool = False, skip_locked: bool = True) -> None:
        self.inside_by_midpoint = inside_by_midpoint
        self.skip_locked = skip_locked
        self.net: dict[str, int] = defaultdict(int)
        self.volume: dict[str, int] = defaultdict(int)
        self.unknown_volume = 0
        self._last_price: dict[str, float] = {}

    def apply(self, trade: OptionTrade) -> Side:
        side = classify(
            trade.price,
            trade.bid,
            trade.ask,
            self._last_price.get(trade.symbol),
            self.inside_by_midpoint,
            self.skip_locked,
        )
        self._last_price[trade.symbol] = trade.price
        self.volume[trade.symbol] += trade.size
        if side is Side.UNKNOWN:
            self.unknown_volume += trade.size
        else:
            self.net[trade.symbol] += side.value * trade.size
        return side

    def extend(self, trades: Iterable[OptionTrade]) -> None:
        for trade in trades:
            self.apply(trade)

    @property
    def unknown_share(self) -> float:
        total = sum(self.volume.values())
        return self.unknown_volume / total if total else 0.0


class Baseline(Enum):
    """Dealer inventory assumed at the open, from the morning's open interest."""

    FLAT = "flat"  # only today's flow counts
    LONG_CALLS_SHORT_PUTS = "long_calls_short_puts"  # the usual open-interest convention
    SHORT_ALL = "short_all"  # customers own everything outstanding


def dealer_position(open_interest: int, is_call: bool, customer_net: int, baseline: Baseline) -> int:
    """Not part of the public repository."""
    return 0
