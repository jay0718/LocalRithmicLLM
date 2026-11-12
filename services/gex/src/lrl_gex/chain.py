"""Latest known state of an option chain, built from market events."""

from collections.abc import Iterable
from dataclasses import dataclass

from lrl_common.contracts import OptionContract
from lrl_common.events import OpenInterest, Quote, Settlement, Trade


@dataclass(frozen=True)
class OptionQuote:
    bid: float | None
    ask: float | None
    ts_ns: int


class ChainState:
    def __init__(self, underlying: str, contracts: Iterable[OptionContract]) -> None:
        self.underlying = underlying
        self.contracts = {contract.symbol: contract for contract in contracts}
        self.spot: float | None = None
        self.now_ns = 0
        self.quotes: dict[str, OptionQuote] = {}
        self.open_interest: dict[str, int] = {}
        self.settlements: dict[str, Settlement] = {}

    def apply(self, event: Trade | Quote | OpenInterest | Settlement) -> None:
        # Time comes from the feed and never moves backward, so replays are deterministic.
        self.now_ns = max(self.now_ns, event.exchange_ts_ns)
        if event.symbol == self.underlying:
            self._apply_underlying(event)
        elif event.symbol in self.contracts:
            if isinstance(event, Quote):
                self._apply_option_quote(event)
            elif isinstance(event, OpenInterest):
                self.open_interest[event.symbol] = event.open_interest
            elif isinstance(event, Settlement):
                self.settlements[event.symbol] = event

    def _apply_underlying(self, event: Trade | Quote | OpenInterest | Settlement) -> None:
        if isinstance(event, Quote) and event.bid_price is not None and event.ask_price is not None:
            self.spot = (event.bid_price + event.ask_price) / 2
        elif isinstance(event, Trade):
            self.spot = event.price

    def _apply_option_quote(self, event: Quote) -> None:
        current = self.quotes.get(event.symbol)
        if current is None or event.exchange_ts_ns >= current.ts_ns:
            self.quotes[event.symbol] = OptionQuote(event.bid_price, event.ask_price, event.exchange_ts_ns)
