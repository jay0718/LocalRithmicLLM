"""A MarketDataSource that plays back a sequence of events."""

import asyncio
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass

from lrl_common.events import OpenInterest, Quote, Trade

MarketEvent = Trade | Quote | OpenInterest
ALL_SYMBOLS = "*"
_YIELD_EVERY = 500


@dataclass(frozen=True)
class FaultConfig:
    """Probability per event of each fault. Faults are deterministic for a given seed."""

    drop: float = 0.0
    duplicate: float = 0.0
    reorder: float = 0.0
    seed: int = 0


def inject_faults(events: Iterable[MarketEvent], faults: FaultConfig) -> Iterator[MarketEvent]:
    """Drop, duplicate or delay events past their successor, as an unreliable feed would."""
    rng = random.Random(faults.seed)
    held: MarketEvent | None = None
    for event in events:
        if rng.random() < faults.drop:
            continue
        if held is None and rng.random() < faults.reorder:
            held = event
            continue
        yield event
        if rng.random() < faults.duplicate:
            yield event
        if held is not None:
            yield held
            held = None
    if held is not None:
        yield held


class ReplaySource:
    """Replays events at a multiple of recorded speed, or as fast as possible when speed is None."""

    def __init__(
        self,
        events: Iterable[MarketEvent],
        speed: float | None = None,
        faults: FaultConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if speed is not None and speed <= 0:
            raise ValueError("speed must be positive, or None for maximum speed")
        self._events = inject_faults(events, faults) if faults else iter(events)
        self._speed = speed
        self._clock = clock
        self._sleep = sleep
        self._symbols: set[str] = set()
        self._closed = False

    async def connect(self) -> None:
        self._closed = False

    async def subscribe(self, symbols: Sequence[str]) -> None:
        self._symbols.update(symbols)

    async def close(self) -> None:
        self._closed = True

    def _is_subscribed(self, event: MarketEvent) -> bool:
        return ALL_SYMBOLS in self._symbols or event.symbol in self._symbols

    async def stream(self) -> AsyncIterator[MarketEvent]:
        first_ts: int | None = None
        started = self._clock()
        for count, event in enumerate(self._events):
            if self._closed:
                return
            if first_ts is None:
                first_ts = event.exchange_ts_ns
            if self._speed is not None:
                # Scheduling from the start time keeps sleep overhead from accumulating.
                due = started + (event.exchange_ts_ns - first_ts) / 1e9 / self._speed
                delay = due - self._clock()
                if delay > 0:
                    await self._sleep(delay)
            if count % _YIELD_EVERY == 0:
                # A replay running behind schedule never sleeps, and must not starve the event loop.
                await asyncio.sleep(0)
            if self._is_subscribed(event):
                yield event
