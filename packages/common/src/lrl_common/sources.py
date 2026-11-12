"""The interface every market data source implements."""

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from .events import OpenInterest, Quote, Trade


class MarketDataSource(Protocol):
    """Lifecycle: connect, subscribe, consume stream, then close."""

    async def connect(self) -> None:
        """Open the session. Raises if the source cannot be reached or rejects the login."""
        ...

    async def subscribe(self, symbols: Sequence[str]) -> None:
        """Start delivering events for symbols. Safe to call more than once."""
        ...

    def stream(self) -> AsyncIterator[Trade | Quote | OpenInterest]:
        """Yield normalized events in arrival order until the source is closed or exhausted."""
        ...

    async def close(self) -> None:
        """Release the session. Safe to call more than once."""
        ...
