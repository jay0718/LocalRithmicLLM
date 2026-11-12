"""Serve GEX for several underlyings from synthetic replay data, with no credentials.

Run with: uvicorn --factory lrl_gex.main:create_app_from_env
"""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime

from fastapi import FastAPI
from lrl_collector.replay import ALL_SYMBOLS, ReplaySource
from lrl_collector.synthetic import PRODUCTS as SYNTHETIC_MARKETS
from lrl_collector.synthetic import SyntheticMarket, generate_history, session_start

from .app import create_app
from .engine import EngineConfig
from .overlay import start_overlay_tasks
from .publisher import PublishStats, publish_loop
from .runtime import PRODUCTS, LiveUpdate, UnderlyingRuntime

_REPLAY_TICKS = 1_000_000


def create_app_from_env() -> FastAPI:
    if os.environ.get("GEX_SOURCE", "replay") == "rithmic":
        from .live import create_live_app_from_env

        return create_live_app_from_env()
    speed = float(os.environ.get("GEX_REPLAY_SPEED", "10"))
    interval = float(os.environ.get("GEX_PUBLISH_INTERVAL_SECONDS", "1"))
    history_sessions = int(os.environ.get("GEX_HISTORY_SESSIONS", "10"))
    # Replay today's session by default so dates on the chart look current. GEX_REPLAY_DATE pins a day.
    pinned = os.environ.get("GEX_REPLAY_DATE")
    replay_day = datetime.fromisoformat(pinned).replace(tzinfo=UTC, hour=15) if pinned else datetime.now(UTC)
    start = session_start(replay_day)
    codes = [code.strip() for code in os.environ.get("GEX_PRODUCTS", "ES,NQ,RTY,YM").split(",") if code.strip()]

    runtimes: dict[str, UnderlyingRuntime] = {}
    sources: list[tuple[UnderlyingRuntime, ReplaySource]] = []
    for index, code in enumerate(codes):
        product = PRODUCTS[code]
        market_config = replace(SYNTHETIC_MARKETS[code], seed=7 + index, start=start)
        market = SyntheticMarket(market_config)
        config = EngineConfig(multiplier=product.multiplier, data_source="synthetic")
        runtime = UnderlyingRuntime(product, market.contracts, config)
        runtime.bars.seed(generate_history(market_config, sessions=history_sessions))
        runtimes[product.symbol] = runtime
        sources.append((runtime, ReplaySource(market.events(_REPLAY_TICKS), speed=speed)))

    async def ingest(runtime: UnderlyingRuntime, source: ReplaySource) -> None:
        await source.connect()
        await source.subscribe([ALL_SYMBOLS])
        async for event in source.stream():
            runtime.apply(event)

    def computer(runtime: UnderlyingRuntime):
        async def compute() -> dict[int | None, LiveUpdate] | None:
            return await asyncio.to_thread(runtime.compute_all) or None

        return compute

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks = [asyncio.create_task(ingest(runtime, source)) for runtime, source in sources]
        tasks += start_overlay_tasks(runtimes)
        tasks += [
            asyncio.create_task(publish_loop(computer(runtime), runtime, interval, PublishStats()))
            for runtime in runtimes.values()
        ]
        try:
            yield
        finally:
            for _, source in sources:
                await source.close()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    return create_app(runtimes, lifespan)
