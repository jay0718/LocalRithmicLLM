"""A MarketDataSource for Rithmic's ticker plant, with heartbeats and automatic reconnects."""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

import websockets
from lrl_common.events import OpenInterest, Quote, SequenceCounter, Trade
from lrl_common.rithmic import tls_context

from ..backoff import Backoff
from ..buffer import BoundedBuffer
from ..quotes import QuoteBook
from . import codec

log = logging.getLogger(__name__)

MarketEvent = Trade | Quote | OpenInterest
_LOGIN_TIMEOUT_SECONDS = 10
_STABLE_AFTER_SECONDS = 30


class SourceStats:
    def __init__(self) -> None:
        self.reconnects = 0
        self.connected = False
        self.last_message_monotonic: float | None = None
        self.messages: dict[str, int] = {}
        self.rejects = 0

    def count(self, kind: str) -> None:
        self.messages[kind] = self.messages.get(kind, 0) + 1

    def feed_age_seconds(self) -> float:
        if self.last_message_monotonic is None:
            return float("inf")
        return time.monotonic() - self.last_message_monotonic


_KIND_NAMES = {
    codec.BEST_BID_OFFER: "quote",
    codec.LAST_TRADE: "trade",
    codec.OPEN_INTEREST: "open_interest",
    codec.END_OF_DAY_PRICES: "settlement",
}


class RithmicSource:
    """Reads market data from Rithmic. connect() raises on a bad login; later drops reconnect automatically."""

    def __init__(
        self,
        uri: str,
        credentials: codec.Credentials,
        exchange: str = "CME",
        exchanges: dict[str, str] | None = None,
        buffer_size: int = 50_000,
        put_timeout_seconds: float = 1.0,
        backoff: Backoff | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._uri = uri
        self._credentials = credentials
        self._exchange = exchange
        self._exchanges = dict(exchanges or {})
        self._buffer: BoundedBuffer[MarketEvent] = BoundedBuffer(buffer_size, put_timeout_seconds)
        self._backoff = backoff or Backoff()
        self._sleep = sleep
        self._symbols: list[str] = []
        self._quotes = QuoteBook()
        self._decoder = codec.Decoder(SequenceCounter.from_clock(), self._quotes)
        self._ws = None
        self._heartbeat_interval = 60.0
        self._run_task: asyncio.Task | None = None
        self._closing = False
        self.stats = SourceStats()

    @property
    def dropped(self) -> int:
        return self._buffer.dropped

    def queue_depth(self) -> int:
        return self._buffer.qsize()

    async def _open_session(self) -> None:
        ssl_context = tls_context() if self._uri.startswith("wss://") else None
        ws = await websockets.connect(self._uri, ssl=ssl_context, open_timeout=_LOGIN_TIMEOUT_SECONDS, max_size=None)
        try:
            await ws.send(codec.login_request(self._credentials))
            frame = await asyncio.wait_for(ws.recv(), _LOGIN_TIMEOUT_SECONDS)
            self._heartbeat_interval = codec.parse_login_response(frame)
            self._quotes.reset()
            for symbol in self._symbols:
                await ws.send(codec.market_data_request(symbol, self.exchange_for(symbol)))
        except BaseException:
            await ws.close()
            raise
        self._ws = ws
        self.stats.connected = True
        log.info("Logged in to %s with %d symbols", self._credentials.system_name, len(self._symbols))

    async def connect(self) -> None:
        self._closing = False
        await self._open_session()
        self._run_task = asyncio.create_task(self._run())

    async def subscribe(self, symbols: Sequence[str]) -> None:
        new = [symbol for symbol in symbols if symbol not in self._symbols]
        self._symbols.extend(new)
        if self._ws is not None:
            for symbol in new:
                await self._ws.send(codec.market_data_request(symbol, self.exchange_for(symbol)))

    def exchange_for(self, symbol: str) -> str:
        return self._exchanges.get(symbol, self._exchange)

    async def _heartbeats(self, ws) -> None:
        while True:
            await asyncio.sleep(max(self._heartbeat_interval / 2, 1))
            await ws.send(codec.heartbeat_request())

    async def _read(self, ws) -> None:
        async for frame in ws:
            kind = codec.template_id(frame)
            if kind in (codec.REJECT, codec.FORCED_LOGOUT):
                self.stats.rejects += 1
                log.warning("Rithmic sent template %d; reconnecting", kind)
                return
            if kind == codec.MARKET_DATA_UPDATE_RESPONSE:
                symbol, codes = codec.parse_subscription_response(frame)
                if codes[:1] != ["0"]:
                    log.warning("Subscription to %s rejected: %s", symbol, codes)
                continue
            event = self._decoder.decode(kind, frame)
            if event is None:
                continue
            self.stats.last_message_monotonic = time.monotonic()
            self.stats.count(_KIND_NAMES[kind])
            await self._buffer.put(event)

    async def _session(self, ws) -> None:
        heartbeats = asyncio.create_task(self._heartbeats(ws))
        try:
            await self._read(ws)
        finally:
            heartbeats.cancel()
            await asyncio.gather(heartbeats, return_exceptions=True)
            self.stats.connected = False
            await ws.close()

    async def _run(self) -> None:
        while not self._closing:
            started = time.monotonic()
            try:
                await self._session(self._ws)
            except (OSError, websockets.ConnectionClosed) as error:
                log.warning("Rithmic connection lost: %s", type(error).__name__)
            self._ws = None
            if self._closing:
                return
            if time.monotonic() - started > _STABLE_AFTER_SECONDS:
                self._backoff.reset()
            await self._reconnect()

    async def _reconnect(self) -> None:
        while not self._closing:
            await self._sleep(self._backoff.next_delay())
            try:
                await self._open_session()
            except (OSError, TimeoutError, websockets.WebSocketException) as error:
                log.warning("Reconnect failed: %s", type(error).__name__)
                continue
            self.stats.reconnects += 1
            return

    async def stream(self) -> AsyncIterator[MarketEvent]:
        while not self._closing:
            get = asyncio.create_task(self._buffer.get())
            waiters = {get} | ({self._run_task} if self._run_task else set())
            done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            if get in done:
                yield get.result()
                continue
            get.cancel()
            self._run_task.result()  # surfaces a fatal error such as a rejected re-login
            return

    async def close(self) -> None:
        self._closing = True
        ws = self._ws
        if ws is not None:
            with contextlib.suppress(websockets.ConnectionClosed):
                await ws.send(codec.logout_request())
            await ws.close()
        if self._run_task is not None:
            self._run_task.cancel()
            await asyncio.gather(self._run_task, return_exceptions=True)
            self._run_task = None
