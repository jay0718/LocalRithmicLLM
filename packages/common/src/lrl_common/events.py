"""Versioned market data events shared by every source and consumer."""

import hashlib
import time
from collections import defaultdict
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    source: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    exchange_ts_ns: int = Field(ge=0)
    seq: int = Field(ge=0)


class Trade(_Event):
    type: Literal["trade"] = "trade"
    price: float
    size: int = Field(ge=0)


class Quote(_Event):
    """Best bid and offer. A side is None when that side has no quote."""

    type: Literal["quote"] = "quote"
    bid_price: float | None = None
    bid_size: int | None = Field(default=None, ge=0)
    ask_price: float | None = None
    ask_size: int | None = Field(default=None, ge=0)


class OpenInterest(_Event):
    type: Literal["open_interest"] = "open_interest"
    open_interest: int = Field(ge=0)


class Settlement(_Event):
    """The exchange settlement price and the trading day it belongs to (YYYYMMDD)."""

    type: Literal["settlement"] = "settlement"
    price: float = Field(gt=0)
    settlement_date: str = Field(pattern=r"^\d{8}$")


MarketEvent = Annotated[Trade | Quote | OpenInterest | Settlement, Field(discriminator="type")]
_adapter: TypeAdapter[Trade | Quote | OpenInterest | Settlement] = TypeAdapter(MarketEvent)


def encode_event(event: "Trade | Quote | OpenInterest | Settlement") -> bytes:
    return event.model_dump_json().encode()


def decode_event(payload: bytes) -> "Trade | Quote | OpenInterest | Settlement":
    """Parse an event. Unknown versions or shapes raise, so consumers can dead-letter them."""
    return _adapter.validate_json(payload)


def idempotency_key(event: "Trade | Quote | OpenInterest | Settlement") -> str:
    """Identify an event by (source, symbol, exchange_ts_ns, seq).

    Fields are length-prefixed so that different field values can never hash the
    same input. seq must come from a SequenceCounter, which makes it unique per
    (source, symbol) across event types.
    """
    digest = hashlib.blake2b(digest_size=16)
    for field in (event.source, event.symbol, str(event.exchange_ts_ns), str(event.seq)):
        data = field.encode()
        digest.update(len(data).to_bytes(4, "big"))
        digest.update(data)
    return digest.hexdigest()


class SequenceCounter:
    """Assign increasing sequence numbers per symbol.

    Live collectors use from_clock(), so a restart cannot reuse earlier numbers.
    Replay passes a fixed start to stay deterministic.
    """

    def __init__(self, start: int = 0) -> None:
        self._next: defaultdict[str, int] = defaultdict(lambda: start)

    @classmethod
    def from_clock(cls) -> "SequenceCounter":
        return cls(start=time.time_ns() // 1000)

    def next(self, symbol: str) -> int:
        value = self._next[symbol]
        self._next[symbol] = value + 1
        return value
