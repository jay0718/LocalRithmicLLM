"""ETF option GEX drawn on a futures chart: QQQ strikes rescaled to NQ points."""

import asyncio
import os
from collections.abc import Mapping
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from .engine import GexSnapshot
from .equity_eod import NY, EodSettings, EquityEod, run_eod_loop
from .flow_live import DEFAULT_NQ_PER_QQQ, LiveFlow, flow_service_from_env
from .runtime import UnderlyingRuntime

# Futures product -> the ETF whose options are overlaid on it.
DEFAULT_OVERLAYS = "NQ:QQQ"


class OverlayStrike(BaseModel):
    strike: float  # in futures points
    source_strike: float  # in ETF dollars
    call_gex: float
    put_gex: float
    net_gex: float


class EquityOverlay(BaseModel):
    symbol: str
    trade_date: str
    source_close: float
    target_close: float
    ratio: float
    # "close": both 4pm closes; "live": the futures' current price, when its 4pm bar is unavailable.
    ratio_basis: Literal["close", "live"]
    expiries: list[str]
    total_gex: float
    call_wall: float | None
    put_wall: float | None
    king_node: float | None
    flip_level: float | None
    contracts_used: int
    contracts_total: int
    prices_missing: int
    prices_pending: int
    series_total: int
    open_interest_source: str
    strikes: list[OverlayStrike]


def overlay_map(spec: str) -> dict[str, str]:
    pairs = (item.split(":", 1) for item in spec.split(",") if ":" in item)
    return {product.strip().upper(): etf.strip().upper() for product, etf in pairs}


def futures_close(runtime: UnderlyingRuntime, trade_date: str) -> float | None:
    """The futures' last price before 4pm ET on the session date, from its minute bars."""
    day = date(int(trade_date[:4]), int(trade_date[4:6]), int(trade_date[6:]))
    close_ns = int(datetime(day.year, day.month, day.day, 16, tzinfo=NY).timestamp() * 1e9)
    window_start = close_ns - 6 * 3600 * 1_000_000_000
    before = [bar for bar in runtime.bars.all_bars() if window_start <= bar.start_ns < close_ns]
    return before[-1].close if before else None


def pick_snapshot(eod: EquityEod, expiries: int | None) -> GexSnapshot:
    """The nearest N expiries, or every fetched expiry when N is None or covers them all."""
    if expiries is not None and 1 <= expiries <= len(eod.nearest):
        return eod.nearest[expiries - 1]
    return eod.snapshot


def map_overlay(
    eod: EquityEod, target_close: float, basis: Literal["close", "live"], expiries: int | None = None
) -> EquityOverlay:
    ratio = target_close / eod.close
    snapshot = pick_snapshot(eod, expiries)

    def scale(level: float | None) -> float | None:
        return None if level is None else level * ratio

    return EquityOverlay(
        symbol=eod.symbol,
        trade_date=eod.trade_date,
        source_close=eod.close,
        target_close=target_close,
        ratio=ratio,
        ratio_basis=basis,
        expiries=snapshot.expiries,
        total_gex=snapshot.total_gex,
        call_wall=scale(snapshot.call_wall),
        put_wall=scale(snapshot.put_wall),
        king_node=scale(snapshot.king_node),
        flip_level=scale(snapshot.flip_level),
        contracts_used=snapshot.contracts_used,
        contracts_total=snapshot.contracts_total,
        prices_missing=eod.prices_missing,
        prices_pending=eod.prices_pending,
        series_total=eod.series_total,
        open_interest_source=eod.open_interest_source,
        strikes=[
            OverlayStrike(
                strike=row.strike * ratio,
                source_strike=row.strike,
                call_gex=row.call_gex,
                put_gex=row.put_gex,
                net_gex=row.net_gex,
            )
            for row in snapshot.strikes
        ],
    )


def overlay_for(runtime: UnderlyingRuntime, expiries: int | None = None) -> EquityOverlay | None:
    eod = runtime.equity
    if eod is None:
        return None
    close = futures_close(runtime, eod.trade_date)
    if close is not None:
        return map_overlay(eod, close, "close", expiries)
    if runtime.chain.spot is not None:
        return map_overlay(eod, runtime.chain.spot, "live", expiries)
    return None


def start_overlay_tasks(runtimes: Mapping[str, UnderlyingRuntime]) -> list[asyncio.Task]:
    """Build each configured ETF's end-of-day GEX in the background, when a Massive key is set."""
    settings = EodSettings.from_env()
    pairs = overlay_map(os.environ.get("EQUITY_OVERLAYS", DEFAULT_OVERLAYS))
    tasks = []
    for runtime in runtimes.values():
        etf = pairs.get(runtime.product.code)
        if etf is None:
            continue
        runtime.equity_symbol = etf
        if settings is None:
            continue

        def keep(result: EquityEod, runtime: UnderlyingRuntime = runtime) -> None:
            runtime.equity = result

        tasks.append(asyncio.create_task(run_eod_loop(etf, settings, keep)))
    # Live flow nodes for the ETF, if configured, attach to the future it is paired with.
    target = next((r for r in runtimes.values() if r.equity_symbol), None)
    if target is not None:

        def center(runtime: UnderlyingRuntime = target) -> float | None:
            # Centre the strike band on the ETF's last close, or on the future's price scaled back.
            if runtime.equity is not None:
                return runtime.equity.close
            return runtime.chain.spot / DEFAULT_NQ_PER_QQQ if runtime.chain.spot else None

        def attach(flow: LiveFlow, runtime: UnderlyingRuntime = target) -> None:
            runtime.flow_live = flow

        service = flow_service_from_env(center)
        if service is not None:
            tasks.append(asyncio.create_task(service(attach)))
    return tasks
