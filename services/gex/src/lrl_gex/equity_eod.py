"""End-of-day GEX for an ETF's options (QQQ for NQ), from free sources, mapped onto a futures price scale.

Open interest per series comes from OCC's public series search. Option closes come from Massive's
daily bars, which the free plan allows at five calls a minute. Only the out-of-the-money side of each
strike is fetched; the other side is priced by put-call parity, since both share one implied volatility.
The GEX engine then runs on these closes exactly as it does for futures options.
"""

import asyncio
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from lrl_common.contracts import OptionContract
from lrl_common.events import OpenInterest, Settlement, Trade
from pydantic import BaseModel

from .chain import ChainState
from .engine import EngineConfig, GexSnapshot, compute_snapshot

log = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
OCC_SERIES_URL = "https://marketdata.theocc.com/series-search?symbolType=U&symbol={symbol}"
MASSIVE_URL = "https://api.massive.com"
SHARES_PER_CONTRACT = 100
_USER_AGENT = "Mozilla/5.0 (compatible; gex-eod)"

Fetch = Callable[[str, dict[str, str]], Awaitable[tuple[int, str]]]


async def http_get(url: str, headers: dict[str, str]) -> tuple[int, str]:
    def call() -> tuple[int, str]:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **headers})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode(errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            # Network trouble (DNS, resets, timeouts) is reported as status 0 so callers can retry.
            return 0, str(error)

    return await asyncio.to_thread(call)


@dataclass(frozen=True)
class Series:
    expiry: str  # YYYYMMDD
    strike: float
    call_oi: int
    put_oi: int


_OCC_ROW = re.compile(
    r"^(?P<product>\S+)\s+(?P<y>\d{4})\s+(?P<m>\d{1,2})\s+(?P<d>\d{1,2})\s+(?P<int>\d+)\s+(?P<dec>\d+)"
    r"\s+[CP](?:\s+[CP])?\s+(?P<call>\d+)\s+(?P<put>\d+)\s+\d+\s*$"
)


def parse_occ_series(text: str, symbol: str) -> list[Series]:
    """Open interest per expiry and strike from OCC's series search text, standard contracts only."""
    series = []
    for line in text.splitlines():
        match = _OCC_ROW.match(line.strip())
        # Adjusted contracts (e.g. QQQ1) have other deliverables, so they are left out.
        if match is None or match["product"] != symbol:
            continue
        strike = int(match["int"]) + int(match["dec"]) / 10 ** len(match["dec"])
        expiry = f"{match['y']}{int(match['m']):02d}{int(match['d']):02d}"
        series.append(Series(expiry, strike, int(match["call"]), int(match["put"])))
    return series


def option_ticker(symbol: str, expiry: str, is_call: bool, strike: float) -> str:
    """OCC-style ticker as Massive spells it, e.g. O:QQQ261113C00690000."""
    return f"O:{symbol}{expiry[2:]}{'C' if is_call else 'P'}{round(strike * 1000):08d}"


class MassiveClient:
    """Daily bars from Massive, kept under the plan's call rate and retried when throttled."""

    def __init__(
        self,
        api_key: str,
        calls_per_minute: int = 5,
        fetch: Fetch = http_get,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._key = api_key
        self._per_minute = calls_per_minute
        self._fetch = fetch
        self._sleep = sleep
        self._clock = clock
        self._calls: deque[float] = deque()

    async def _throttle(self) -> None:
        while len(self._calls) >= self._per_minute:
            wait = 60 - (self._clock() - self._calls[0])
            if wait <= 0:
                self._calls.popleft()
                continue
            await self._sleep(wait)
        self._calls.append(self._clock())

    async def previous_close(self, ticker: str) -> tuple[date, float] | None:
        """The ticker's latest completed daily bar as (session date, close), or None if it has none.

        The free plan serves the latest session only through this endpoint, not by date.
        """
        url = f"{MASSIVE_URL}/v2/aggs/ticker/{ticker}/prev?adjusted=true"
        for attempt in range(6):
            await self._throttle()
            status, body = await self._fetch(url, {"Authorization": f"Bearer {self._key}"})
            if status == 429:
                await self._sleep(60)
                continue
            if status == 0 or status >= 500:
                # Transient network or server trouble: back off and try again.
                await self._sleep(min(15 * 2**attempt, 240))
                continue
            if status != 200:
                raise RuntimeError(f"Massive returned HTTP {status} for {ticker}")
            results = json.loads(body).get("results") or []
            if not results:
                return None
            bar = results[0]
            return datetime.fromtimestamp(bar["t"] / 1000, NY).date(), float(bar["c"])
        raise RuntimeError(f"Massive kept failing for {ticker}")


class EquityEod(BaseModel):
    """One session's end-of-day GEX for an ETF, in its own prices."""

    symbol: str
    trade_date: str  # YYYYMMDD
    close: float
    snapshot: GexSnapshot  # every fetched expiry
    # The same session limited to the nearest 1, 2, ... expiries (index 0 is the next expiry alone).
    nearest: list[GexSnapshot] = []
    prices_missing: int
    # Series whose price has not been fetched yet; above zero while a build is still running.
    prices_pending: int = 0
    series_total: int = 0
    open_interest_source: str = "OCC"
    built_at: str


def _close_ns(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 16, tzinfo=NY).timestamp() * 1e9)


def _expiry_date(expiry: str) -> date:
    return date(int(expiry[:4]), int(expiry[4:6]), int(expiry[6:]))


def choose_series(series: Iterable[Series], trade_date: date, close: float, expiries: int, strike_pct: float):
    """Strikes near the close with open interest, in the nearest expiries after the session."""
    after = trade_date.strftime("%Y%m%d")
    upcoming = sorted({s.expiry for s in series if s.expiry > after})[:expiries]
    return [
        s
        for s in series
        if s.expiry in upcoming and abs(s.strike - close) <= close * strike_pct and (s.call_oi or s.put_oi)
    ]


def _otm_ticker(symbol: str, series: Series, close: float) -> tuple[str, bool]:
    """The out-of-the-money side trades more and prices the strike's volatility more reliably."""
    call_is_otm = series.strike >= close
    return option_ticker(symbol, series.expiry, call_is_otm, series.strike), call_is_otm


def compute_equity_eod(
    symbol: str, session: tuple[date, float], chosen: list[Series], cache: dict[str, float | None]
) -> EquityEod | None:
    """GEX from the closes fetched so far; series not fetched yet are counted as pending."""
    trade_date, close = session
    now_ns = _close_ns(trade_date)
    session_day = trade_date.strftime("%Y%m%d")
    chain_contracts: list[OptionContract] = []
    events: list[Trade | OpenInterest | Settlement] = [
        Trade(source="massive", symbol=symbol, exchange="US", exchange_ts_ns=now_ns, seq=0, price=close, size=0)
    ]
    missing = pending = 0
    for seq, s in enumerate(chosen, start=1):
        ticker, call_is_otm = _otm_ticker(symbol, s, close)
        if ticker not in cache:
            pending += 1
            continue
        otm = cache[ticker]
        if otm is None or otm <= 0:
            missing += 1
            continue
        # Put-call parity with the close as the forward: C - P = S - K.
        call = otm if call_is_otm else otm + close - s.strike
        put = otm - close + s.strike if call_is_otm else otm
        expiry_ns = _close_ns(_expiry_date(s.expiry))
        for is_call, price, oi in ((True, call, s.call_oi), (False, put, s.put_oi)):
            if price <= 0 or oi == 0:
                continue
            contract = OptionContract(
                option_ticker(symbol, s.expiry, is_call, s.strike), symbol, s.expiry, expiry_ns, s.strike, is_call
            )
            chain_contracts.append(contract)
            common = {"source": "massive", "symbol": contract.symbol, "exchange": "OPRA", "exchange_ts_ns": now_ns}
            events.append(OpenInterest(**common, seq=seq, open_interest=oi))
            events.append(Settlement(**common, seq=seq, price=price, settlement_date=session_day))
    chain = ChainState(symbol, chain_contracts)
    for event in events:
        chain.apply(event)
    config = EngineConfig(multiplier=SHARES_PER_CONTRACT, rate=0.0, settlement_fallback=True, data_source="massive+occ")
    snapshot = compute_snapshot(chain, config)
    if snapshot is None:
        return None
    nearest = [compute_snapshot(chain, replace(config, max_expiries=n)) for n in range(1, len(snapshot.expiries))]
    return EquityEod(
        symbol=symbol,
        trade_date=session_day,
        close=close,
        snapshot=snapshot,
        nearest=[item for item in nearest if item is not None],
        prices_missing=missing,
        prices_pending=pending,
        series_total=len(chosen),
        built_at=datetime.now(UTC).isoformat(),
    )


async def build_equity_eod(
    symbol: str,
    session: tuple[date, float],
    client: MassiveClient,
    occ_text: str,
    expiries: int = 4,
    strike_pct: float = 0.025,
    cache: dict[str, float | None] | None = None,
    on_price: Callable[[], None] | None = None,
    on_progress: Callable[[EquityEod], None] | None = None,
    progress_every: int = 5,
) -> EquityEod | None:
    """GEX from one session's closes; session is the ETF's (date, close).

    Prices are fetched nearest expiry first and nearest strike first, and on_progress gets a partial
    result every few prices, so the next expiry is usable long before the whole build finishes.
    """
    cache = {} if cache is None else cache
    trade_date, close = session
    chosen = choose_series(parse_occ_series(occ_text, symbol), trade_date, close, expiries, strike_pct)

    def progress() -> None:
        if on_progress and (partial := compute_equity_eod(symbol, session, chosen, cache)) is not None:
            on_progress(partial)

    if cache:
        progress()
    fetched = 0
    for s in sorted(chosen, key=lambda item: (item.expiry, abs(item.strike - close))):
        ticker, _ = _otm_ticker(symbol, s, close)
        if ticker in cache:
            continue
        latest = await client.previous_close(ticker)
        # An option that did not trade this session reports an older bar, which would be stale.
        cache[ticker] = latest[1] if latest is not None and latest[0] == trade_date else None
        fetched += 1
        if on_price:
            on_price()
        if fetched % progress_every == 0:
            progress()
    return compute_equity_eod(symbol, session, chosen, cache)


@dataclass(frozen=True)
class EodSettings:
    api_key: str
    directory: Path
    calls_per_minute: int = 5
    expiries: int = 4
    strike_pct: float = 0.025

    @classmethod
    def from_env(cls) -> "EodSettings | None":
        key = os.environ.get("MASSIVE_API_KEY", "")
        if not key:
            return None
        return cls(
            api_key=key,
            directory=Path(os.environ.get("EQUITY_EOD_DIR", "data/eod")),
            calls_per_minute=int(os.environ.get("MASSIVE_CALLS_PER_MINUTE", "5")),
            expiries=int(os.environ.get("EQUITY_EOD_EXPIRIES", "4")),
            strike_pct=float(os.environ.get("EQUITY_EOD_STRIKE_PCT", "0.025")),
        )


class EodStore:
    """Saved end-of-day results and the per-contract closes fetched so far, as JSON files."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, symbol: str, day: str, suffix: str = "json") -> Path:
        return self.directory / f"{symbol}-{day}.{suffix}"

    def latest(self, symbol: str) -> EquityEod | None:
        files = sorted(self.directory.glob(f"{symbol}-[0-9]*[0-9].json"))
        return EquityEod.model_validate_json(files[-1].read_text()) if files else None

    def has(self, symbol: str, day: date) -> bool:
        return self._path(symbol, day.strftime("%Y%m%d")).exists()

    def save(self, result: EquityEod) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(result.symbol, result.trade_date).write_text(result.model_dump_json())
        self._path(result.symbol, result.trade_date, "closes.json").unlink(missing_ok=True)

    def load_closes(self, symbol: str, day: date) -> dict[str, float | None]:
        path = self._path(symbol, day.strftime("%Y%m%d"), "closes.json")
        return json.loads(path.read_text()) if path.exists() else {}

    def save_closes(self, symbol: str, day: date, closes: dict[str, float | None]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(symbol, day.strftime("%Y%m%d"), "closes.json").write_text(json.dumps(closes))


async def fetch_occ(symbol: str, fetch: Fetch = http_get) -> str:
    status, body = await fetch(OCC_SERIES_URL.format(symbol=symbol), {})
    if status != 200:
        raise RuntimeError(f"OCC series search returned HTTP {status}")
    return body


async def run_eod_loop(
    symbol: str,
    settings: EodSettings,
    on_result: Callable[[EquityEod], None],
    check_every: float = 900,
    retry_after: float = 60,
) -> None:
    """Keep the latest session's result built and saved; fetching resumes where it stopped after a restart."""
    store = EodStore(settings.directory)
    if (saved := store.latest(symbol)) is not None:
        on_result(saved)
    client = MassiveClient(settings.api_key, settings.calls_per_minute)
    while True:
        try:
            session = await client.previous_close(symbol)
            if session is not None and not store.has(symbol, session[0]):
                day = session[0]
                closes = store.load_closes(symbol, day)
                log.info("Building %s end-of-day GEX for %s (%d closes cached)", symbol, day, len(closes))
                result = await build_equity_eod(
                    symbol,
                    session,
                    client,
                    await fetch_occ(symbol),
                    settings.expiries,
                    settings.strike_pct,
                    cache=closes,
                    on_price=lambda day=day, closes=closes: store.save_closes(symbol, day, closes),
                    on_progress=on_result,
                )
                if result is not None and result.prices_pending == 0:
                    store.save(result)
                    on_result(result)
                    log.info("Saved %s end-of-day GEX for %s", symbol, day)
        except Exception:
            log.exception("%s end-of-day GEX failed; retrying in %.0fs", symbol, retry_after)
            await asyncio.sleep(retry_after)
            continue
        await asyncio.sleep(check_every)
