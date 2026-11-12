"""Gamma exposure from a chain's live quotes and daily open interest.

The calculation itself is kept private; this module defines its inputs and outputs.
"""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel

from .chain import ChainState

_NS_PER_YEAR = 365 * 86_400 * 1_000_000_000
_FLIP_GRID_POINTS = 241
_FLIP_RANGE = 0.15


class DealerConvention(StrEnum):
    """The assumed dealer position. Real positioning is not observable."""

    LONG_CALLS_SHORT_PUTS = "long_calls_short_puts"
    SHORT_CALLS_LONG_PUTS = "short_calls_long_puts"

    def signs(self) -> tuple[float, float]:
        return (1.0, -1.0) if self is DealerConvention.LONG_CALLS_SHORT_PUTS else (-1.0, 1.0)


@dataclass(frozen=True)
class EngineConfig:
    multiplier: float = 50.0
    rate: float = 0.04
    stale_after_seconds: float = 60.0
    convention: DealerConvention = DealerConvention.LONG_CALLS_SHORT_PUTS
    expiry: str | None = None
    data_source: str = "live"
    # Price options from their last settlement when there is no usable quote, as during a halt.
    settlement_fallback: bool = False
    # Only the nearest N unexpired expiries, or all of them when None.
    max_expiries: int | None = None


class StrikeGex(BaseModel):
    strike: float
    call_gex: float
    put_gex: float
    net_gex: float


class GexSnapshot(BaseModel):
    data_source: str
    underlying: str
    spot: float
    as_of_ns: int
    convention: DealerConvention
    expiry: str | None
    total_gex: float
    flip_level: float | None
    call_wall: float | None
    put_wall: float | None
    king_node: float | None
    king_node_gex: float | None
    strikes: list[StrikeGex]
    contracts_total: int
    contracts_used: int
    missing_quotes: int
    stale_quotes: int
    missing_open_interest: int
    unpriced: int
    priced_from_settlement: int = 0
    expiries: list[str] = []
    oldest_settlement: str | None = None


def compute_snapshot(chain: ChainState, config: EngineConfig | None = None) -> GexSnapshot | None:
    """The exposure calculation is not part of the public repository; this build returns None."""
    return None
