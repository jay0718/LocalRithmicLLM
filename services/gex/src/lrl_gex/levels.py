"""Central pivot range from the prior CME session."""

from collections.abc import Sequence
from datetime import date

from lrl_common.bars import Bar, aggregate, trading_date
from pydantic import BaseModel


class CentralPivotRange(BaseModel):
    """Levels for today, from the previous session's high, low and close. tc is always the upper bound."""

    session_date: date
    high: float
    low: float
    close: float
    pivot: float
    bc: float
    tc: float
    r1: float
    s1: float
    r2: float
    s2: float
    width_pct: float


def central_pivot_range(high: float, low: float, close: float, session: date) -> CentralPivotRange:
    pivot = (high + low + close) / 3
    bc = (high + low) / 2
    tc = 2 * pivot - bc
    lower, upper = sorted((bc, tc))
    return CentralPivotRange(
        session_date=session,
        high=high,
        low=low,
        close=close,
        pivot=pivot,
        bc=lower,
        tc=upper,
        r1=2 * pivot - low,
        s1=2 * pivot - high,
        r2=pivot + (high - low),
        s2=pivot - (high - low),
        width_pct=(upper - lower) / pivot * 100,
    )


def prior_session_cpr(minute_bars: Sequence[Bar]) -> CentralPivotRange | None:
    """CPR from the last complete session before the one the newest bar belongs to."""
    if not minute_bars:
        return None
    current = trading_date(minute_bars[-1].start_ns)
    daily = [bar for bar in aggregate(minute_bars, "1d") if trading_date(bar.start_ns) < current]
    if not daily:
        return None
    prior = daily[-1]
    return central_pivot_range(prior.high, prior.low, prior.close, trading_date(prior.start_ns))
