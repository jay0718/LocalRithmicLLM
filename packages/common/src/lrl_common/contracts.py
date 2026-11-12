"""Option contract definitions shared by data sources and the GEX engine."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionContract:
    symbol: str
    underlying: str
    expiry: str  # YYYYMMDD
    expiry_ts_ns: int
    strike: float
    is_call: bool
