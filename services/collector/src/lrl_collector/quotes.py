"""Turn partial best-bid-offer updates into full quotes."""

from dataclasses import dataclass, field

BID = 1
ASK = 2


@dataclass
class _Side:
    price: float | None = None
    size: int | None = None


@dataclass
class _Book:
    bid: _Side = field(default_factory=_Side)
    ask: _Side = field(default_factory=_Side)


class QuoteBook:
    """Rithmic sends only the sides that changed (presence bits) or were removed (clear bits).

    Consumers get the complete best bid and offer every time, so they never need
    earlier messages to interpret a quote.
    """

    def __init__(self) -> None:
        self._books: dict[str, _Book] = {}

    def apply(
        self,
        symbol: str,
        present: int,
        cleared: int,
        bid_price: float,
        bid_size: int,
        ask_price: float,
        ask_size: int,
    ) -> tuple[float | None, int | None, float | None, int | None]:
        book = self._books.setdefault(symbol, _Book())
        for bit, side, price, size in ((BID, book.bid, bid_price, bid_size), (ASK, book.ask, ask_price, ask_size)):
            if cleared & bit:
                side.price = side.size = None
            elif present & bit:
                side.price, side.size = price, size
        return book.bid.price, book.bid.size, book.ask.price, book.ask.size

    def reset(self) -> None:
        """Forget state after a reconnect, since the server resends snapshots."""
        self._books.clear()
