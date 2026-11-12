"""Live GEX from Rithmic: real bar history at startup, then streaming quotes and open interest.

Only read-only templates are sent (login, search, bar history, market data), all
through the collector codec's allowlist.
"""

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import websockets
from fastapi import FastAPI
from lrl_collector.rithmic import codec
from lrl_collector.rithmic.source import RithmicSource
from lrl_common.bars import NEW_YORK, Bar
from lrl_common.contracts import OptionContract
from lrl_common.rithmic import binding, tls_context

from .app import create_app
from .engine import EngineConfig
from .overlay import start_overlay_tasks
from .publisher import PublishStats, publish_loop
from .runtime import PRODUCTS, LiveUpdate, UnderlyingRuntime

log = logging.getLogger(__name__)
_LOGIN_GAP_SECONDS = 4  # Rithmic refuses logins made in quick succession
_REPLY_TIMEOUT = 20


@dataclass(frozen=True)
class LiveProduct:
    code: str
    exchange: str
    # Text that finds this product's options with Search Symbols, or None if the feed has none.
    option_search: str | None
    option_name_prefixes: tuple[str, ...] = ()
    # Optional allowlist of option product codes, for example ("ES",) on Rithmic Test,
    # which only sends open interest for quarterly ES options.
    option_products: tuple[str, ...] = ()


# Option names on Rithmic production (Apex), checked 2026-11-11. Weeklies, end-of-month and
# quarterly options on the E-mini share the future's multiplier; micro options do not.
LIVE_PRODUCTS = {
    "ES": LiveProduct("ES", "CME", "S&P 500", ("e-mini s&p 500", "cme end of month options on e")),
    "NQ": LiveProduct("NQ", "CME", "Nasdaq", ("e-mini nasdaq-100",)),
    "RTY": LiveProduct("RTY", "CME", "Russell", ("e-mini russell 2000",)),
    # Mini-Dow options (OYM) use a strike format that is not verified yet.
    "YM": LiveProduct("YM", "CBOT", None),
}
_EXCLUDED_NAMES = ("event", "micro", "test", "midcap", "dividend", "s&p 400")


@dataclass(frozen=True)
class LiveSettings:
    uri: str
    credentials: codec.Credentials
    codes: list[str]
    history_days: int = 7
    expiries: int = 4
    strike_pct: float = 0.025
    option_products: tuple[str, ...] | None = None

    @classmethod
    def from_env(cls) -> "LiveSettings":
        def env(name: str, default: str | None = None) -> str:
            value = os.environ.get(name, default)
            if not value:
                raise SystemExit(f"Set {name}")
            return value

        return cls(
            uri=env("RITHMIC_URI"),
            credentials=codec.Credentials(
                env("RITHMIC_USER"),
                env("RITHMIC_PASSWORD"),
                env("RITHMIC_SYSTEM_NAME"),
                env("RITHMIC_APP_NAME"),
                env("RITHMIC_APP_VERSION", "0.1.0"),
            ),
            codes=[c.strip() for c in env("GEX_PRODUCTS", "ES,NQ,RTY,YM").split(",") if c.strip()],
            history_days=int(env("GEX_LIVE_HISTORY_DAYS", "7")),
            expiries=int(env("GEX_LIVE_EXPIRIES", "4")),
            strike_pct=float(env("GEX_LIVE_STRIKE_PCT", "0.025")),
            option_products=tuple(
                c.strip() for c in os.environ.get("GEX_LIVE_OPTION_PRODUCTS", "").split(",") if c.strip()
            )
            or None,
        )


@asynccontextmanager
async def _session(settings: LiveSettings, plant: int) -> AsyncIterator[websockets.ClientConnection]:
    ws = await websockets.connect(settings.uri, ssl=tls_context(), open_timeout=10, max_size=None)
    try:
        await ws.send(codec.login_request(settings.credentials, plant))
        codec.parse_login_response(await asyncio.wait_for(ws.recv(), 10))
        yield ws
        await ws.send(codec.logout_request())
    finally:
        await ws.close()


def bar_from_reply(reply) -> Bar:
    # Rithmic stamps a minute bar with its closing time; bars here are keyed by their start.
    return Bar(
        start_ns=(reply.marker - 60) * 1_000_000_000,
        open=reply.open_price,
        high=reply.high_price,
        low=reply.low_price,
        close=reply.close_price,
        volume=reply.volume,
        trades=reply.num_trades,
    )


async def load_history(
    settings: LiveSettings, symbols: dict[str, str], seconds: int | None = None
) -> dict[str, list[Bar]]:
    """Real 1-minute bars for each symbol from Rithmic's history plant, over the last ``seconds``
    (default: the configured number of days)."""
    reply_type = binding("response_time_bar_replay_pb2").ResponseTimeBarReplay
    end = int(time.time())
    start = end - (seconds if seconds is not None else settings.history_days * 86_400)
    history: dict[str, list[Bar]] = {}
    async with _session(settings, codec.HISTORY_PLANT) as ws:
        for symbol, exchange in symbols.items():
            await ws.send(codec.minute_bars_request(symbol, exchange, start, end))
            bars: list[Bar] = []
            while True:
                frame = await asyncio.wait_for(ws.recv(), _REPLY_TIMEOUT)
                if codec.template_id(frame) != codec.TIME_BAR_REPLAY_RESPONSE:
                    continue
                reply = reply_type()
                reply.ParseFromString(frame)
                if list(reply.rp_code):
                    break
                bars.append(bar_from_reply(reply))
            history[symbol] = bars
            log.info("Loaded %d history bars for %s", len(bars), symbol)
    return history


@dataclass(frozen=True)
class OptionListing:
    symbol: str
    product: str
    expiry: str
    name: str


def parse_option(listing: OptionListing, underlying: str) -> OptionContract | None:
    """Option symbols end in ' C7600' or ' P7600'."""
    _, _, tail = listing.symbol.rpartition(" ")
    if len(tail) < 2 or tail[0] not in "CP":
        return None
    try:
        strike = float(tail[1:])
    except ValueError:
        return None
    day = datetime.strptime(listing.expiry, "%Y%m%d").date()
    # Approximation: equity index options are treated as expiring at 4pm New York time.
    expires = datetime(day.year, day.month, day.day, 16, tzinfo=NEW_YORK)
    return OptionContract(
        symbol=listing.symbol,
        underlying=underlying,
        expiry=listing.expiry,
        expiry_ts_ns=int(expires.timestamp() * 1e9),
        strike=strike,
        is_call=tail[0] == "C",
    )


def choose_chain(
    listings: list[OptionListing],
    product: LiveProduct,
    underlying: str,
    underlying_expiry: date,
    spot: float,
    now: datetime,
    expiries: int,
    strike_pct: float,
    products: tuple[str, ...] = (),
) -> list[OptionContract]:
    """The nearest unexpired expiries that settle into this futures contract, within strike_pct of spot."""
    prefixes = tuple(prefix.lower() for prefix in product.option_name_prefixes)
    contracts: dict[str, list[OptionContract]] = {}
    for listing in listings:
        name = listing.name.lower()
        if not name.startswith(prefixes) or any(word in name for word in _EXCLUDED_NAMES):
            continue
        if products and listing.product not in products:
            continue
        if listing.expiry > underlying_expiry.strftime("%Y%m%d"):
            continue
        contract = parse_option(listing, underlying)
        if contract is None or contract.expiry_ts_ns <= now.timestamp() * 1e9:
            continue
        if abs(contract.strike / spot - 1) <= strike_pct:
            contracts.setdefault(listing.expiry, []).append(contract)
    nearest = sorted(contracts)[:expiries]
    return [contract for expiry in nearest for contract in contracts[expiry]]


async def search_options(settings: LiveSettings, text: str, exchange: str) -> list[OptionListing]:
    reply_type = binding("response_search_symbols_pb2").ResponseSearchSymbols
    found = []
    async with _session(settings, codec.TICKER_PLANT) as ws:
        await ws.send(codec.search_options_request(text, exchange))
        while True:
            frame = await asyncio.wait_for(ws.recv(), _REPLY_TIMEOUT)
            if codec.template_id(frame) != codec.SEARCH_SYMBOLS_RESPONSE:
                continue
            reply = reply_type()
            reply.ParseFromString(frame)
            if list(reply.rp_code):
                break
            found.append(OptionListing(reply.symbol, reply.product_code, reply.expiration_date, reply.symbol_name))
    return found


# CME equity index futures expire on the third Friday of the contract month.
_MONTH_CODES = "FGHJKMNQUVXZ"


def futures_expiry(symbol: str) -> date:
    month = _MONTH_CODES.index(symbol[-2]) + 1
    year = 2020 + int(symbol[-1])
    first = date(year, month, 1)
    first_friday = first + timedelta(days=(4 - first.weekday()) % 7)
    return first_friday + timedelta(days=14)


def create_live_app_from_env() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = LiveSettings.from_env()
    interval = float(os.environ.get("GEX_PUBLISH_INTERVAL_SECONDS", "1"))
    runtimes: dict[str, UnderlyingRuntime] = {}
    exchanges: dict[str, str] = {}
    for code in settings.codes:
        product = PRODUCTS[code]
        live = LIVE_PRODUCTS[code]
        runtime = UnderlyingRuntime(product, [], EngineConfig(multiplier=product.multiplier, data_source="rithmic"))
        runtime.follow_market_hours = True
        runtimes[product.symbol] = runtime
        exchanges[product.symbol] = live.exchange
    source = RithmicSource(settings.uri, settings.credentials, exchanges=exchanges)
    tasks: list[asyncio.Task] = []

    async def start() -> None:
        """Retry startup with backoff. Rithmic refuses logins made too soon after earlier sessions."""
        delay = 15.0
        while True:
            try:
                await run()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Live startup failed; retrying in %.0fs", delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)

    async def run() -> None:
        history = await load_history(settings, exchanges)
        option_symbols: list[str] = []
        for symbol, runtime in runtimes.items():
            bars = history.get(symbol, [])
            runtime.bars.seed(bars)
            if bars:
                # Until the first live quote, price comes from the last real bar.
                runtime.chain.spot = bars[-1].close
                runtime.chain.now_ns = bars[-1].start_ns + 60_000_000_000
            live = LIVE_PRODUCTS[runtime.product.code]
            if not bars or live.option_search is None:
                continue
            await asyncio.sleep(_LOGIN_GAP_SECONDS)
            listings = await search_options(settings, live.option_search, live.exchange)
            chain = choose_chain(
                listings,
                live,
                symbol,
                futures_expiry(symbol),
                bars[-1].close,
                datetime.now(UTC),
                settings.expiries,
                settings.strike_pct,
                settings.option_products or live.option_products,
            )
            runtime.chain.contracts = {contract.symbol: contract for contract in chain}
            for contract in chain:
                exchanges[contract.symbol] = live.exchange
            option_symbols += [contract.symbol for contract in chain]
            log.info(
                "Tracking %d %s options across expiries %s",
                len(chain),
                symbol,
                ", ".join(sorted({contract.expiry for contract in chain})),
            )
        await asyncio.sleep(_LOGIN_GAP_SECONDS)
        await source.subscribe([*runtimes, *option_symbols])
        await source.connect()
        tasks.append(asyncio.create_task(backfill_after_startup()))
        async for event in source.stream():
            for runtime in runtimes.values():
                if event.symbol == runtime.product.symbol or event.symbol in runtime.chain.contracts:
                    runtime.apply(event)

    async def backfill(reason: str, lookback: int = 3 * 3600) -> None:
        """Fetch recent bars from Rithmic's history plant and merge them, filling minutes the live
        feed never delivered."""
        # Rithmic refuses a login made too soon after another one.
        await asyncio.sleep(_LOGIN_GAP_SECONDS)
        try:
            history = await load_history(settings, {symbol: exchanges[symbol] for symbol in runtimes}, lookback)
        except Exception:
            log.exception("Bar backfill (%s) failed", reason)
            return
        for symbol, bars in history.items():
            added = runtimes[symbol].bars.backfill(bars)
            log.info("Backfilled %d missed minutes for %s (%s)", added, symbol, reason)

    async def backfill_after_reconnects(check_every: float = 5.0) -> None:
        """A dropped connection leaves no hole: the minutes it missed are fetched after each reconnect."""
        seen = source.stats.reconnects
        while True:
            await asyncio.sleep(check_every)
            if source.stats.reconnects != seen:
                seen = source.stats.reconnects
                await backfill("after a reconnect")

    async def backfill_after_startup(delays: tuple[float, ...] = (75.0, 300.0)) -> None:
        """History is loaded before the live subscription starts (option chains are set up in
        between), so the minutes in that gap are fetched once the live feed is running: first when
        the startup minute has closed, then again a few minutes later in case Rithmic was slow to
        publish it."""
        waited = 0.0
        for delay in delays:
            await asyncio.sleep(delay - waited)
            waited = delay
            await backfill("after startup")

    def computer(runtime: UnderlyingRuntime):
        async def compute() -> dict[int | None, LiveUpdate] | None:
            return await asyncio.to_thread(runtime.compute_all) or None

        return compute

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks.append(asyncio.create_task(start()))
        tasks.extend(start_overlay_tasks(runtimes))
        tasks.append(asyncio.create_task(backfill_after_reconnects()))
        tasks.extend(
            asyncio.create_task(publish_loop(computer(runtime), runtime, interval, PublishStats()))
            for runtime in runtimes.values()
        )
        try:
            yield
        finally:
            await source.close()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    return create_app(runtimes, lifespan)
