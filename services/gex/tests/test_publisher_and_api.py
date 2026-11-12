import pytest
from fastapi.testclient import TestClient
from lrl_common.bars import Bar
from lrl_common.events import Trade
from lrl_gex.app import create_app
from lrl_gex.engine import DealerConvention, EngineConfig, GexSnapshot, StrikeGex
from lrl_gex.main import create_app_from_env
from lrl_gex.publisher import PublishStats, SnapshotHub, publish_loop
from lrl_gex.runtime import PRODUCTS, LiveUpdate, UnderlyingRuntime
from starlette.websockets import WebSocketDisconnect


def snapshot(as_of_ns: int = 1) -> GexSnapshot:
    return GexSnapshot(
        data_source="test",
        underlying="ES",
        spot=100,
        as_of_ns=as_of_ns,
        convention=DealerConvention.LONG_CALLS_SHORT_PUTS,
        expiry=None,
        total_gex=1,
        flip_level=None,
        call_wall=None,
        put_wall=None,
        king_node=None,
        king_node_gex=None,
        strikes=[],
        contracts_total=0,
        contracts_used=0,
        missing_quotes=0,
        stale_quotes=0,
        missing_open_interest=0,
        unpriced=0,
    )


async def test_hub_keeps_only_newest_for_slow_subscribers() -> None:
    hub = SnapshotHub()
    slow = hub.subscribe()
    fast = hub.subscribe()
    hub.publish(snapshot(1))
    assert (await fast.get()).as_of_ns == 1
    hub.publish(snapshot(2))
    hub.publish(snapshot(3))
    assert (await slow.get()).as_of_ns == 3
    assert (await fast.get()).as_of_ns == 3
    assert hub.latest.as_of_ns == 3


async def test_unsubscribed_queue_gets_nothing() -> None:
    hub = SnapshotHub()
    queue = hub.subscribe()
    hub.unsubscribe(queue)
    hub.publish(snapshot())
    assert queue.empty()


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


async def test_cadence_accounts_for_compute_time() -> None:
    fake = FakeTime()

    async def compute() -> GexSnapshot:
        fake.now += 0.2
        return snapshot()

    stats = PublishStats()
    await publish_loop(compute, SnapshotHub(), 1.0, stats, fake.clock, fake.sleep, max_iterations=3)
    assert fake.sleeps == pytest.approx([0.8, 0.8, 0.8])
    assert stats.published == 3
    assert stats.skipped_ticks == 0
    assert stats.last_compute_seconds == pytest.approx(0.2)


async def test_slow_compute_skips_ticks_instead_of_queueing() -> None:
    fake = FakeTime()
    durations = iter([2.5, 0.1])

    async def compute() -> GexSnapshot:
        fake.now += next(durations)
        return snapshot()

    stats = PublishStats()
    await publish_loop(compute, SnapshotHub(), 1.0, stats, fake.clock, fake.sleep, max_iterations=2)
    assert stats.skipped_ticks == 2
    assert fake.sleeps[0] == pytest.approx(0.5)
    assert fake.sleeps[1] == pytest.approx(0.9)


async def test_nothing_published_without_a_snapshot() -> None:
    fake = FakeTime()

    async def compute() -> None:
        return None

    hub, stats = SnapshotHub(), PublishStats()
    await publish_loop(compute, hub, 1.0, stats, fake.clock, fake.sleep, max_iterations=1)
    assert hub.latest is None and stats.published == 0


def runtimes_with(*symbols: str) -> dict[str, UnderlyingRuntime]:
    return {
        PRODUCTS[code].symbol: UnderlyingRuntime(PRODUCTS[code], [], EngineConfig(multiplier=PRODUCTS[code].multiplier))
        for code in symbols
    }


def update(snapshot_value: GexSnapshot | None, underlying: str = "ESZ6", bar: Bar | None = None) -> LiveUpdate:
    return LiveUpdate(underlying=underlying, snapshot=snapshot_value, bar=bar)


def test_lists_underlyings_in_order() -> None:
    client = TestClient(create_app(runtimes_with("ES", "NQ")))
    assert client.get("/underlyings").json() == [
        {"symbol": "ESZ6", "product": "ES", "name": "E-mini S&P 500", "overlay": None, "expiries": []},
        {"symbol": "NQZ6", "product": "NQ", "name": "E-mini Nasdaq-100", "overlay": None, "expiries": []},
    ]


def test_latest_is_503_until_available_and_per_underlying() -> None:
    runtimes = runtimes_with("ES", "NQ")
    client = TestClient(create_app(runtimes))
    assert client.get("/snapshots/latest").status_code == 503
    runtimes["NQZ6"].hub.latest = update(snapshot(5), "NQZ6")
    assert client.get("/snapshots/latest", params={"underlying": "NQZ6"}).json()["as_of_ns"] == 5
    assert client.get("/snapshots/latest").status_code == 503
    assert client.get("/snapshots/latest", params={"underlying": "XX"}).status_code == 404


def test_bars_route_returns_recent_bars() -> None:
    runtimes = runtimes_with("ES")
    client = TestClient(create_app(runtimes))
    assert client.get("/bars").json() == []
    runtimes["ESZ6"].apply(
        Trade(source="t", symbol="ESZ6", exchange="CME", exchange_ts_ns=60 * 10**9, seq=0, price=100, size=2)
    )
    body = client.get("/bars", params={"limit": 5}).json()
    assert body[0]["close"] == 100 and body[0]["volume"] == 2


def test_bars_by_interval_and_cpr_levels() -> None:
    from lrl_collector.synthetic import PRODUCTS as MARKETS
    from lrl_collector.synthetic import generate_history

    runtimes = runtimes_with("ES")
    client = TestClient(create_app(runtimes))
    assert client.get("/levels/cpr").status_code == 503
    runtimes["ESZ6"].bars.seed(generate_history(MARKETS["ES"], sessions=3))
    minutes = client.get("/bars", params={"interval": "1m", "limit": 5000}).json()
    fives = client.get("/bars", params={"interval": "5m", "limit": 5000}).json()
    days = client.get("/bars", params={"interval": "1d"}).json()
    assert len(minutes) > len(fives) > len(days) == 4
    assert len(minutes) == 5000
    assert sum(b["volume"] for b in fives) == sum(b.volume for b in runtimes["ESZ6"].bars.all_bars())
    assert client.get("/bars", params={"interval": "2m"}).status_code == 422
    cpr = client.get("/levels/cpr").json()
    assert cpr["session_date"] == "2026-11-06"
    assert (cpr["high"], cpr["low"], cpr["close"]) == (days[-2]["high"], days[-2]["low"], days[-2]["close"])
    assert cpr["bc"] <= cpr["tc"]


def test_websocket_sends_latest_on_connect() -> None:
    runtimes = runtimes_with("ES")
    runtimes["ESZ6"].hub.latest = update(snapshot(9))
    with TestClient(create_app(runtimes)).websocket_connect("/ws/live") as websocket:
        assert websocket.receive_json()["snapshot"]["as_of_ns"] == 9


def test_websocket_rejects_unknown_underlying() -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        TestClient(create_app(runtimes_with("ES"))).websocket_connect("/ws/live?underlying=XX") as websocket,
    ):
        websocket.receive_json()


def test_disconnected_websocket_is_unsubscribed() -> None:
    runtimes = runtimes_with("ES")
    runtimes["ESZ6"].hub.latest = update(snapshot())
    with TestClient(create_app(runtimes)) as client:
        with client.websocket_connect("/ws/live") as websocket:
            websocket.receive_json()
        assert runtimes["ESZ6"].hub._subscribers == set()


def test_replay_date_can_be_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEX_PRODUCTS", "ES")
    monkeypatch.setenv("GEX_HISTORY_SESSIONS", "1")
    monkeypatch.setenv("GEX_REPLAY_DATE", "2026-11-14")  # a Saturday replays Friday's session
    client = TestClient(create_app_from_env())
    last_history_bar = client.get("/bars", params={"limit": 1}).json()[-1]
    from datetime import UTC, datetime

    assert datetime.fromtimestamp(last_history_bar["start_ns"] / 1e9, UTC).isoformat() == "2026-11-13T14:29:00+00:00"


def test_websocket_rejects_bad_expiry_count() -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        TestClient(create_app(runtimes_with("ES"))).websocket_connect("/ws/live?expiries=99") as websocket,
    ):
        websocket.receive_json()


def test_equity_overlay_endpoint() -> None:
    from lrl_gex.equity_eod import EquityEod

    runtimes = runtimes_with("ES", "NQ")
    nq = runtimes["NQZ6"]
    nq.equity_symbol = "QQQ"
    client = TestClient(create_app(runtimes))
    assert client.get("/overlays/equity", params={"underlying": "ESZ6"}).status_code == 404
    assert client.get("/overlays/equity", params={"underlying": "NQZ6"}).status_code == 503
    nq.equity = EquityEod(
        symbol="QQQ",
        trade_date="20261111",
        close=690.0,
        snapshot=snapshot().model_copy(
            update={"spot": 690.0, "strikes": [StrikeGex(strike=690.0, call_gex=2e6, put_gex=-1e6, net_gex=1e6)]}
        ),
        prices_missing=0,
        built_at="2026-11-11T22:00:00+00:00",
    )
    nq.chain.spot = 28290.0
    body = client.get("/overlays/equity", params={"underlying": "NQZ6"}).json()
    assert body["ratio_basis"] == "live"
    assert body["strikes"][0]["strike"] == pytest.approx(28290.0)
    assert body["strikes"][0]["source_strike"] == 690.0
    assert client.get("/underlyings").json()[1]["overlay"] == "QQQ"
