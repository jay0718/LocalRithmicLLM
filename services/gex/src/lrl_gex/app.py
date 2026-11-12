"""HTTP and WebSocket access to GEX snapshots and price bars, per underlying."""

import os
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from lrl_common.bars import Bar, Interval, aggregate
from pydantic import BaseModel

from .engine import GexSnapshot
from .flow import FlowRules
from .flow_history import NY, FlowHistory, FlowStore, NodeFrame
from .levels import CentralPivotRange, prior_session_cpr
from .overlay import EquityOverlay, futures_close, overlay_for
from .runtime import LiveUpdate, UnderlyingRuntime


class UnderlyingOut(BaseModel):
    symbol: str
    product: str
    name: str
    # ETF whose options can be overlaid on this future, if any.
    overlay: str | None = None
    # Tracked expiries that have not expired yet, nearest first (YYYYMMDD).
    expiries: list[str] = []


MAX_EXPIRY_CHOICE = 20


class FlowHistoryOut(FlowHistory):
    # Future price per ETF dollar for the session (future's 4pm price / ETF spot then), None if unknown.
    ratio: float | None
    # The same for the overnight board, from the previous session's close.
    overnight_ratio: float | None = None


def ratio_at(runtime: UnderlyingRuntime, frame: NodeFrame) -> float | None:
    """Future price per ETF dollar at a frame's minute, from the future's minute bars."""
    bars = [bar for bar in runtime.bars.all_bars() if bar.start_ns <= frame.ts_ns]
    if bars and frame.ts_ns - bars[-1].start_ns < 10 * 60 * 1_000_000_000:
        return bars[-1].close / frame.spot
    return runtime.chain.spot / frame.spot if runtime.chain.spot else None


def with_ratios(runtime: UnderlyingRuntime, history: FlowHistory, ratio: float | None) -> FlowHistoryOut:
    overnight_ratio = None
    if history.overnight is not None:
        prior_day = datetime.fromtimestamp(history.overnight.ts_ns / 1e9, NY).strftime("%Y%m%d")
        prior_close = futures_close(runtime, prior_day)
        overnight_ratio = prior_close / history.overnight.spot if prior_close is not None else None
    return FlowHistoryOut(**history.model_dump(), ratio=ratio, overnight_ratio=overnight_ratio)


def create_app(
    runtimes: Mapping[str, UnderlyingRuntime],
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
    flow_store: FlowStore | None = None,
) -> FastAPI:
    app = FastAPI(title="LocalRithmicLLM GEX", lifespan=lifespan)
    flow_store = flow_store or FlowStore(Path(os.environ.get("FLOW_DIR", "data/flow")))
    default = next(iter(runtimes), None)

    def runtime_for(underlying: str | None) -> UnderlyingRuntime:
        runtime = runtimes.get(underlying or default or "")
        if runtime is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown underlying: {underlying}")
        return runtime

    @app.get("/underlyings")
    def list_underlyings() -> list[UnderlyingOut]:
        return [
            UnderlyingOut(
                symbol=symbol,
                product=runtime.product.code,
                name=runtime.product.name,
                overlay=runtime.equity_symbol,
                expiries=runtime.upcoming_expiries(),
            )
            for symbol, runtime in runtimes.items()
        ]

    @app.get("/snapshots/latest")
    def latest_snapshot(
        underlying: str | None = None, expiries: int | None = Query(default=None, ge=1, le=MAX_EXPIRY_CHOICE)
    ) -> GexSnapshot:
        latest = runtime_for(underlying).hub_for(expiries).latest
        if latest is None or latest.snapshot is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No snapshot is available yet")
        return latest.snapshot

    @app.get("/bars")
    def recent_bars(
        underlying: str | None = None,
        interval: Interval = "1m",
        limit: int = Query(default=300, ge=1, le=20000),
        start_ns: int | None = None,
        end_ns: int | None = None,
    ) -> list[Bar]:
        """Recent bars, oldest first, including the one still forming; optionally within [start_ns, end_ns)."""
        bars = runtime_for(underlying).bars.all_bars()
        if start_ns is not None or end_ns is not None:
            bars = [
                bar
                for bar in bars
                if (start_ns is None or bar.start_ns >= start_ns) and (end_ns is None or bar.start_ns < end_ns)
            ]
        return aggregate(bars, interval)[-limit:]

    @app.get("/levels/cpr")
    def cpr_levels(underlying: str | None = None) -> CentralPivotRange:
        levels = prior_session_cpr(runtime_for(underlying).bars.all_bars())
        if levels is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No completed prior session yet")
        return levels

    @app.get("/live/latest")
    def latest_update(
        underlying: str | None = None, expiries: int | None = Query(default=None, ge=1, le=MAX_EXPIRY_CHOICE)
    ) -> LiveUpdate:
        latest = runtime_for(underlying).hub_for(expiries).latest
        if latest is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No data is available yet")
        return latest

    @app.get("/overlays/equity")
    def equity_overlay(
        underlying: str | None = None, expiries: int | None = Query(default=None, ge=1, le=MAX_EXPIRY_CHOICE)
    ) -> EquityOverlay:
        """End-of-day GEX of the ETF paired with this future, rescaled to the future's prices."""
        runtime = runtime_for(underlying)
        if runtime.equity_symbol is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No ETF overlay is configured for this underlying")
        overlay = overlay_for(runtime, expiries)
        if overlay is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The ETF overlay has not been built yet")
        return overlay

    @app.get("/flow/dates")
    def flow_dates(underlying: str | None = None) -> list[str]:
        """Sessions with a replayed flow history for this future's ETF, oldest first."""
        runtime = runtime_for(underlying)
        return flow_store.dates(runtime.equity_symbol) if runtime.equity_symbol else []

    @app.get("/flow/history")
    def flow_history(
        date: str, underlying: str | None = None, skip_inside: bool = True, skip_locked: bool = True
    ) -> FlowHistoryOut:
        """Minute-by-minute flow nodes for one session, with the ETF-to-future price ratio for that day.

        skip_inside and skip_locked choose the trade filters (see FlowRules); both on by default.
        """
        runtime = runtime_for(underlying)
        rules = FlowRules(skip_inside, skip_locked)
        history = flow_store.load(runtime.equity_symbol, date, rules) if runtime.equity_symbol else None
        if history is None or not history.frames:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No flow history for that session")
        close = futures_close(runtime, date.replace("-", ""))
        last = history.frames[-1]
        ratio = close / last.spot if close is not None else None
        return with_ratios(runtime, history, ratio)

    @app.get("/flow/live")
    def flow_live(
        underlying: str | None = None,
        skip_inside: bool = True,
        skip_locked: bool = True,
        stream: bool = False,
    ) -> FlowHistoryOut:
        """Today's live flow so far: one frame per market minute (or per 10 seconds with
        stream=true), the last one still updating."""
        runtime = runtime_for(underlying)
        flow = runtime.flow_live
        if flow is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Live flow is not running")
        history = flow.history(FlowRules(skip_inside, skip_locked), stream)
        first = history.frames[0] if history.frames else history.overnight
        if first is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Live flow has no frames yet")
        # One ratio for the whole session, from its first frame, so node lines stay level.
        return with_ratios(runtime, history, ratio_at(runtime, first))

    @app.websocket("/ws/bars")
    async def bar_stream(websocket: WebSocket, underlying: str | None = None) -> None:
        """The forming bar as soon as a trade changes it, with the bar that finished before it."""
        runtime = runtimes.get(underlying or default or "")
        if runtime is None:
            await websocket.close(code=4404, reason="Unknown underlying")
            return
        await websocket.accept()
        hub = runtime.bar_hub
        queue = hub.subscribe()
        try:
            if hub.latest is not None:
                await websocket.send_text(hub.latest.model_dump_json())
            while True:
                tick = await queue.get()
                await websocket.send_text(tick.model_dump_json())
        except WebSocketDisconnect:
            pass
        finally:
            hub.unsubscribe(queue)

    @app.websocket("/ws/flow")
    async def flow_stream(
        websocket: WebSocket,
        underlying: str | None = None,
        skip_inside: bool = True,
        skip_locked: bool = True,
    ) -> None:
        runtime = runtimes.get(underlying or default or "")
        if runtime is None or runtime.flow_live is None:
            await websocket.close(code=4404, reason="Live flow is not running")
            return
        await websocket.accept()
        hub = runtime.flow_live.variant(FlowRules(skip_inside, skip_locked)).hub
        queue = hub.subscribe()
        try:
            if hub.latest is not None:
                await websocket.send_text(hub.latest.model_dump_json())
            while True:
                frame = await queue.get()
                await websocket.send_text(frame.model_dump_json())
        except WebSocketDisconnect:
            pass
        finally:
            hub.unsubscribe(queue)

    @app.websocket("/ws/live")
    async def live_stream(websocket: WebSocket, underlying: str | None = None, expiries: int | None = None) -> None:
        runtime = runtimes.get(underlying or default or "")
        if runtime is None:
            await websocket.close(code=4404, reason="Unknown underlying")
            return
        if expiries is not None and not 1 <= expiries <= MAX_EXPIRY_CHOICE:
            await websocket.close(code=4400, reason="expiries must be between 1 and 20")
            return
        await websocket.accept()
        hub = runtime.hub_for(expiries)
        queue = hub.subscribe()
        try:
            if hub.latest is not None:
                await websocket.send_text(hub.latest.model_dump_json())
            while True:
                update = await queue.get()
                await websocket.send_text(update.model_dump_json())
        except WebSocketDisconnect:
            pass
        finally:
            hub.unsubscribe(queue)

    return app
