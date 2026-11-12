import asyncio
import sys
import types
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from lrl_gex.app import create_app
from lrl_gex.engine import EngineConfig
from lrl_gex.flow_history import NY, FlowStore, FlowTrade
from lrl_gex.flow_live import (
    DatabentoGateway,
    front_session,
    strike_band,
)
from lrl_gex.runtime import PRODUCTS, UnderlyingRuntime

DAY = date(2026, 11, 10)


PRIOR = date(2026, 11, 9)


def at(hour: int, minute: int, second: int = 0, day: date = DAY) -> int:
    return int(datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=NY).timestamp()) * 10**9


def quotes(ts: int) -> list[FlowTrade]:
    """Inside-spread prints that only set quotes, around spot 675."""
    rows = []
    for k, call, put in ((670, 6.0, 1.0), (675, 2.5, 2.5), (680, 1.0, 6.0)):
        rows.append(FlowTrade(ts, f"QQQ261110C{k * 1000:08d}", call, 1, call - 0.05, call + 0.05))
        rows.append(FlowTrade(ts, f"QQQ261110P{k * 1000:08d}", put, 1, put - 0.05, put + 0.05))
    return rows


def buy(ts: int, size: int = 100) -> FlowTrade:
    return FlowTrade(ts, "QQQ261110C00680000", 1.05, size, 1.0, 1.05)


async def no_sleep(_: float) -> None:
    await asyncio.sleep(0)


def test_front_session_rolls_at_the_close() -> None:
    assert front_session(datetime(2026, 11, 10, 16, 14, tzinfo=NY)) == DAY
    assert front_session(datetime(2026, 11, 10, 16, 15, tzinfo=NY)) == date(2026, 11, 11)
    # Friday after the close and the weekend roll to Monday.
    assert front_session(datetime(2026, 11, 13, 17, 0, tzinfo=NY)) == date(2026, 11, 16)
    assert front_session(datetime(2026, 11, 15, 12, 0, tzinfo=NY)) == date(2026, 11, 16)


def test_strike_band() -> None:
    assert strike_band(675.0, 0.04) == (648, 703)


@dataclass
class Level:
    bid_px: int
    ask_px: int


@dataclass
class TCBBOMsg:
    instrument_id: int
    ts_event: int
    price: int
    size: int
    levels: list[Level] = field(default_factory=lambda: [Level(1_000_000_000, 1_050_000_000)])


@dataclass
class SymbolMappingMsg:
    instrument_id: int
    stype_out_symbol: str


class BentoError(Exception):
    pass


class Store:
    def __init__(self, path: str | None = None) -> None:
        self.path = path


def fake_databento(sessions: list[list[object]], starts: list[datetime], downloads: list[str]) -> types.ModuleType:
    """Each Live connection replays the next scripted session; an exception object is raised."""
    module = types.ModuleType("databento")
    module.TCBBOMsg, module.SymbolMappingMsg, module.BentoError = TCBBOMsg, SymbolMappingMsg, BentoError
    script = iter(sessions)

    class Live:
        def __init__(self, key: str) -> None:
            self.records = next(script)

        def subscribe(self, start: datetime, **_: object) -> None:
            starts.append(start)

        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            for record in self.records:
                if isinstance(record, Exception):
                    raise record
                yield record

    class Timeseries:
        def get_range(self, path: str | None = None, **_: object) -> Store:
            downloads.append(path or "")
            if path:
                open(path, "wb").close()
            return Store(path)

    class Historical:
        def __init__(self, key: str) -> None:
            self.timeseries = Timeseries()

    class DBNStore:
        @staticmethod
        def from_file(path) -> Store:
            return Store(str(path))

    module.Live, module.Historical, module.DBNStore = Live, Historical, DBNStore
    return module


async def test_stream_reconnects_from_the_last_trade_without_duplicates(monkeypatch) -> None:
    mapping = SymbolMappingMsg(7, "QQQ   261110C00680000")
    t1, t2, t3 = at(9, 31), at(9, 32), at(9, 33)
    price = 1_050_000_000
    starts: list[datetime] = []
    sessions = [
        [mapping, TCBBOMsg(7, t1, price, 10), TCBBOMsg(7, t2, price, 20), BentoError("drop")],
        # The reconnect replays from t2: the t2 trade again (dropped), then a new t2 trade and t3.
        [mapping, TCBBOMsg(7, t2, price, 20), TCBBOMsg(7, t2, 1_000_000_000, 5), TCBBOMsg(7, t3, price, 30)],
    ]
    monkeypatch.setitem(sys.modules, "databento", fake_databento(sessions, starts, []))
    gateway = DatabentoGateway("key", reconnect_delay=0)
    start = datetime(2026, 11, 10, 0, 0, tzinfo=NY)
    got = [trade async for trade in gateway.stream(["QQQ   261110C00680000"], start)]
    assert [(t.ts_ns, t.size) for t in got] == [(t1, 10), (t2, 20), (t2, 5), (t3, 30)]
    assert got[0].symbol == "QQQ261110C00680000" and got[0].price == pytest.approx(1.05)
    assert starts == [start, datetime.fromtimestamp(t2 / 1e9, UTC)]


def test_history_is_bought_once_and_reused_from_the_cache(monkeypatch, tmp_path) -> None:
    downloads: list[str] = []
    monkeypatch.setitem(sys.modules, "databento", fake_databento([], [], downloads))
    # Only the download count matters here; converting stores to trades needs pandas.
    monkeypatch.setattr("lrl_gex.flow_dbn.trades_from_store", lambda *stores: iter(()))
    gateway = DatabentoGateway("key", cache=tmp_path)
    symbols = ["QQQ   261110C00670000", "QQQ   261110P00680000"]
    start, end = datetime(2026, 10, 6, tzinfo=NY), datetime(2026, 11, 10, tzinfo=NY)
    list(gateway.history(symbols, start, end))
    list(gateway.history(symbols, start, end))
    assert len(downloads) == 1 and downloads[0].startswith(str(tmp_path))


def test_store_keeps_each_filter_combination_apart(tmp_path) -> None:
    from lrl_gex.flow import FlowRules
    from lrl_gex.flow_history import FlowHistory

    store = FlowStore(tmp_path)
    plain = FlowHistory(symbol="QQQ", expiry="20261110", session_date="2026-11-10", frames=[])
    other = plain.model_copy(update={"expiry": "other"})
    store.save(plain)
    store.save(other, FlowRules(skip_locked=False))
    assert store.dates("QQQ") == ["2026-11-10"]
    assert store.load("QQQ", "2026-11-10").expiry == "20261110"
    assert store.load("QQQ", "2026-11-10", FlowRules(skip_locked=False)).expiry == "other"
    assert store.load("QQQ", "2026-11-10", FlowRules(skip_inside=False)) is None


def test_bar_stream_sends_each_change_with_the_finished_bar() -> None:
    from lrl_common.events import Quote, Trade

    nq = UnderlyingRuntime(PRODUCTS["NQ"], [], EngineConfig())
    nq.bars.session_hours_only = False
    queue = nq.bar_hub.subscribe()

    def trade(ts: int, price: float) -> Trade:
        return Trade(source="test", symbol="NQZ6", exchange="CME", exchange_ts_ns=ts, seq=0, price=price, size=1)

    nq.apply(trade(at(10, 0, 5), 28_000.0))
    nq.apply(trade(at(10, 0, 50), 28_010.25))
    # A quote that leaves the bar as it is sends nothing.
    published = nq.bar_hub.latest
    nq.apply(
        Quote(
            source="test",
            symbol="NQZ6",
            exchange="CME",
            exchange_ts_ns=at(10, 0, 55),
            seq=0,
            bid_price=28_010.0,
            ask_price=28_010.5,
        )
    )
    assert nq.bar_hub.latest is published
    # The next minute's first trade: the message carries the finished 10:00 bar with its final close.
    nq.apply(trade(at(10, 1, 1), 28_005.0))
    tick = queue.get_nowait()
    assert tick.bar.start_ns == at(10, 1) and tick.previous is not None
    assert (tick.previous.start_ns, tick.previous.close, tick.previous.high) == (at(10, 0), 28_010.25, 28_010.25)

    client = TestClient(create_app({"NQZ6": nq}))
    with client.websocket_connect("/ws/bars") as ws:
        assert ws.receive_json()["previous"]["close"] == 28_010.25
