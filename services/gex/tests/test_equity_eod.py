import json
from datetime import date, datetime

import pytest
from lrl_gex.equity_eod import (
    NY,
    MassiveClient,
    choose_series,
    option_ticker,
    parse_occ_series,
)
from lrl_gex.overlay import futures_close, overlay_map

OCC = """Series Search Results for QQQ

\t\tSeries/contract\t\tStrike\t\t\tOpen Interest\t\t\t
ProductSymbol\tyear\tMonth\tDay\tInteger\tDec\tC/P\tCall\tPut\tPosition Limit\t
QQQ   \t\t2026\t11\t10\t690\t000\tC P \t5\t5\t180000000
QQQ   \t\t2026\t11\t12\t680\t000\tC P \t100\t900\t180000000
QQQ   \t\t2026\t11\t12\t690\t000\tC P \t500\t400\t180000000
QQQ   \t\t2026\t11\t12\t690\t500\tC P \t0\t0\t180000000
QQQ   \t\t2026\t11\t12\t700\t000\tC P \t800\t50\t180000000
QQQ   \t\t2026\t11\t12\t760\t000\tC P \t9000\t9000\t180000000
QQQ1  \t\t2026\t11\t12\t690\t000\tC P \t7\t7\t180000000
QQQ   \t\t2026\t11\t13\t690\t000\tC P \t300\t300\t180000000
"""


SESSION = date(2026, 11, 11)


BAR_TS = int(datetime(2026, 11, 11, 16, tzinfo=NY).timestamp() * 1000)


def test_parses_occ_series_and_skips_adjusted_contracts() -> None:
    series = parse_occ_series(OCC, "QQQ")
    assert len(series) == 7
    assert series[1].expiry == "20261112"
    assert (series[1].strike, series[1].call_oi, series[1].put_oi) == (680.0, 100, 900)
    assert series[3].strike == 690.5


def test_chooses_near_strikes_with_open_interest_in_upcoming_expiries() -> None:
    chosen = choose_series(parse_occ_series(OCC, "QQQ"), SESSION, 690.0, expiries=1, strike_pct=0.025)
    # Expired 11/10 is out, 11/13 is beyond one expiry, 760 is too far, 690.5 has no open interest.
    assert [(s.expiry, s.strike) for s in chosen] == [("20261112", 680.0), ("20261112", 690.0), ("20261112", 700.0)]


def test_option_ticker_matches_massive_format() -> None:
    assert option_ticker("QQQ", "20261113", True, 690) == "O:QQQ261113C00690000"
    assert option_ticker("QQQ", "20261113", False, 690.5) == "O:QQQ261113P00690500"


class FakeMassive:
    def __init__(self, closes: dict[str, tuple[date, float] | None]) -> None:
        self.closes = closes
        self.urls: list[str] = []

    async def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, str]:
        assert headers["Authorization"] == "Bearer key"
        self.urls.append(url)
        ticker = url.split("/ticker/")[1].split("/")[0]
        found = self.closes.get(ticker)
        results = [] if found is None else [{"t": _ts(found[0]), "c": found[1]}]
        return 200, json.dumps({"results": results})


def _ts(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 16, tzinfo=NY).timestamp() * 1000)


async def _no_sleep(_: float) -> None:
    return None


async def test_client_keeps_under_the_call_rate_and_retries_throttling() -> None:
    now = [0.0]
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    replies = iter([(429, "{}"), *[(200, json.dumps({"results": [{"t": BAR_TS, "c": 1.0}]}))] * 3])

    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, str]:
        return next(replies)

    client = MassiveClient("key", calls_per_minute=2, fetch=fetch, sleep=sleep, clock=lambda: now[0])
    assert await client.previous_close("QQQ") == (SESSION, 1.0)
    assert waits == [60]
    await client.previous_close("QQQ")
    await client.previous_close("QQQ")
    # Third call in the same minute window waits for the oldest to age out.
    assert len(waits) == 2 and waits[1] > 0


async def test_client_raises_on_refusal() -> None:
    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, str]:
        return 403, '{"status":"NOT_AUTHORIZED"}'

    with pytest.raises(RuntimeError, match="403"):
        await MassiveClient("key", fetch=fetch, sleep=_no_sleep).previous_close("QQQ")


def test_overlay_map_parses_pairs() -> None:
    assert overlay_map("NQ:QQQ, es:spy") == {"NQ": "QQQ", "ES": "SPY"}
    assert overlay_map("") == {}


def test_futures_close_uses_the_last_bar_before_4pm() -> None:
    from lrl_common.bars import Bar
    from lrl_gex.engine import EngineConfig
    from lrl_gex.runtime import PRODUCTS, UnderlyingRuntime

    runtime = UnderlyingRuntime(PRODUCTS["NQ"], [], EngineConfig())

    def at(hour: int, minute: int, close: float) -> Bar:
        start = int(datetime(2026, 11, 11, hour, minute, tzinfo=NY).timestamp() * 1e9)
        return Bar(start_ns=start, open=close, high=close, low=close, close=close, volume=1, trades=1)

    runtime.bars.seed([at(15, 58, 1.0), at(15, 59, 2.0), at(16, 0, 3.0)])
    assert futures_close(runtime, "20261111") == 2.0
    assert futures_close(runtime, "20261112") is None


async def test_client_retries_network_and_server_errors() -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    replies = iter(
        [(0, "DNS failure"), (502, "bad gateway"), (200, json.dumps({"results": [{"t": BAR_TS, "c": 2.0}]}))]
    )

    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, str]:
        return next(replies)

    client = MassiveClient("key", calls_per_minute=100, fetch=fetch, sleep=sleep)
    assert await client.previous_close("QQQ") == (SESSION, 2.0)
    assert waits == [15, 30]
