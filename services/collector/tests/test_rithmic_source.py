"""RithmicSource against a fake ticker plant. Skipped without the Rithmic kit bindings."""

import asyncio

import pytest
from lrl_common.events import OpenInterest, Quote, Trade
from lrl_common.rithmic import RithmicKitMissing, binding

try:
    binding("base_pb2")
except RithmicKitMissing:
    pytest.skip("Rithmic kit bindings are not available", allow_module_level=True)

from fake_rithmic import FakeRithmic, bbo, end_of_day, frame, open_interest, serve, trade  # noqa: E402
from lrl_collector.backoff import Backoff  # noqa: E402
from lrl_collector.rithmic import codec  # noqa: E402
from lrl_collector.rithmic.source import RithmicSource  # noqa: E402
from lrl_common.events import Settlement  # noqa: E402

CREDENTIALS = codec.Credentials("user", "pw-123", "Rithmic Test", "LocalRithmicLLM", "0.1.0")


def source_for(url: str, **kwargs) -> RithmicSource:
    return RithmicSource(url, CREDENTIALS, backoff=Backoff(rng=lambda: 0.0), **kwargs)


async def take(source: RithmicSource, count: int, timeout: float = 5) -> list:
    events = []

    async def run() -> None:
        async for event in source.stream():
            events.append(event)
            if len(events) == count:
                return

    await asyncio.wait_for(run(), timeout)
    return events


async def test_streams_normalized_events() -> None:
    fake = FakeRithmic(
        sessions=[
            [
                bbo(
                    "ESZ6",
                    1_800_000_000,
                    usecs=250,
                    presence_bits=3,
                    bid_price=6000,
                    bid_size=4,
                    ask_price=6000.25,
                    ask_size=9,
                ),
                bbo("ESZ6", 1_800_000_001, presence_bits=1, bid_price=5999.75, bid_size=2),
                trade("ESZ6", 6000.25, 3, source_ssboe=1_800_000_002, source_nsecs=17),
                open_interest("ESZ6 C7600", 312, 1_800_000_003),
            ]
        ]
    )
    server, url = await serve(fake)
    source = source_for(url)
    await source.subscribe(["ESZ6", "ESZ6 C7600"])
    await source.connect()
    first, second, third, fourth = await take(source, 4)
    await source.close()
    server.close()

    assert isinstance(first, Quote) and first.exchange_ts_ns == 1_800_000_000_000_250_000
    assert (first.bid_price, first.ask_price, first.source) == (6000, 6000.25, "rithmic")
    assert (second.bid_price, second.bid_size, second.ask_price, second.ask_size) == (5999.75, 2, 6000.25, 9)
    assert isinstance(third, Trade) and third.exchange_ts_ns == 1_800_000_002_000_000_017
    assert isinstance(fourth, OpenInterest) and fourth.open_interest == 312
    assert second.seq == first.seq + 1
    assert fake.subscribed[0] == ["ESZ6", "ESZ6 C7600"]
    assert source.stats.messages == {"quote": 2, "trade": 1, "open_interest": 1}


async def test_rejected_login_raises_on_connect() -> None:
    server, url = await serve(FakeRithmic(login_codes=[["13", "permission denied"]]))
    with pytest.raises(codec.LoginRejected) as error:
        await source_for(url).connect()
    server.close()
    assert error.value.codes == ["13", "permission denied"]


async def test_reconnects_and_resubscribes() -> None:
    fake = FakeRithmic(
        sessions=[[bbo("ESZ6", 1, presence_bits=1, bid_price=1, bid_size=1)], [trade("ESZ6", 2, 1, ssboe=2)]],
        close_after_script=True,
    )
    server, url = await serve(fake)
    source = source_for(url)
    await source.subscribe(["ESZ6"])
    await source.connect()
    quote, traded = await take(source, 2)
    await source.close()
    server.close()
    assert isinstance(quote, Quote) and isinstance(traded, Trade)
    assert source.stats.reconnects >= 1
    assert fake.subscribed[1] == ["ESZ6"]


async def test_quote_state_resets_after_reconnect() -> None:
    fake = FakeRithmic(
        sessions=[
            [bbo("ESZ6", 1, presence_bits=3, bid_price=1, bid_size=1, ask_price=2, ask_size=1)],
            [bbo("ESZ6", 2, presence_bits=1, bid_price=3, bid_size=1)],
        ],
        close_after_script=True,
    )
    server, url = await serve(fake)
    source = source_for(url)
    await source.subscribe(["ESZ6"])
    await source.connect()
    _, after = await take(source, 2)
    await source.close()
    server.close()
    assert (after.bid_price, after.ask_price) == (3, None)


async def test_rejected_relogin_stops_the_stream() -> None:
    fake = FakeRithmic(
        login_codes=[["0"], ["13", "permission denied"]],
        sessions=[[trade("ES", 1, 1, ssboe=1)]],
        close_after_script=True,
    )
    server, url = await serve(fake)
    source = source_for(url)
    await source.subscribe(["ES"])
    await source.connect()
    with pytest.raises(codec.LoginRejected):
        await take(source, 5)
    await source.close()
    server.close()


async def test_sends_heartbeats() -> None:
    fake = FakeRithmic(heartbeat_interval=2)
    server, url = await serve(fake)
    source = source_for(url)
    await source.connect()
    await asyncio.sleep(1.3)
    await source.close()
    server.close()
    assert (0, codec.HEARTBEAT) in fake.received


async def test_close_logs_out() -> None:
    fake = FakeRithmic()
    server, url = await serve(fake)
    source = source_for(url)
    await source.connect()
    await source.close()
    await asyncio.sleep(0.05)
    server.close()
    assert fake.received[-1] == (0, codec.LOGOUT)


async def test_full_buffer_drops_and_counts() -> None:
    fake = FakeRithmic(sessions=[[trade("ES", i, 1, ssboe=i) for i in range(1, 6)]])
    server, url = await serve(fake)
    source = source_for(url, buffer_size=2, put_timeout_seconds=0.01)
    await source.subscribe(["ES"])
    await source.connect()
    await asyncio.sleep(0.3)
    assert source.dropped == 3
    assert [e.price for e in await take(source, 2)] == [1, 2]
    await source.close()
    server.close()


async def test_only_market_data_templates_are_ever_sent() -> None:
    fake = FakeRithmic(heartbeat_interval=2, sessions=[[trade("ES", 1, 1, ssboe=1)]])
    server, url = await serve(fake)
    source = source_for(url)
    await source.subscribe(["ES", "NQ"])
    await source.connect()
    await take(source, 1)
    await asyncio.sleep(1.3)
    await source.close()
    await asyncio.sleep(0.05)
    server.close()
    assert fake.templates() <= codec.ALLOWED_OUTBOUND
    assert {codec.LOGIN, codec.MARKET_DATA_UPDATE, codec.HEARTBEAT, codec.LOGOUT} <= fake.templates()


@pytest.mark.parametrize(
    ("module", "cls", "template"),
    [
        ("request_new_order_pb2", "RequestNewOrder", 312),
        ("request_cancel_order_pb2", "RequestCancelOrder", 316),
        ("request_login_pb2", "RequestLogin", 10),  # a login request relabeled with an order template id
    ],
)
def test_order_templates_cannot_be_encoded(module: str, cls: str, template: int) -> None:
    message = getattr(binding(module), cls)()
    message.template_id = template if template != 10 else 312
    with pytest.raises(codec.ForbiddenTemplate):
        codec.encode(message)


def test_credentials_repr_hides_password() -> None:
    assert "pw-123" not in repr(CREDENTIALS)


def test_frames_have_no_length_prefix() -> None:
    raw = codec.heartbeat_request()
    message = binding("request_heartbeat_pb2").RequestHeartbeat()
    message.ParseFromString(raw)
    assert message.template_id == codec.HEARTBEAT
    assert raw == frame("request_heartbeat_pb2", "RequestHeartbeat", template_id=18)


async def test_zero_bid_and_ask_mean_no_quote_and_settlements_decode() -> None:
    fake = FakeRithmic(
        sessions=[
            [
                bbo("ESZ6 C7650", 1, presence_bits=3, bid_price=0, bid_size=0, ask_price=0, ask_size=0),
                end_of_day("ESZ6 C7650", 111.5, "20261109"),
            ]
        ]
    )
    server, url = await serve(fake)
    source = source_for(url)
    await source.subscribe(["ESZ6 C7650"])
    await source.connect()
    quote, settlement = await take(source, 2)
    await source.close()
    server.close()
    assert (quote.bid_price, quote.bid_size, quote.ask_price, quote.ask_size) == (None, None, None, None)
    assert isinstance(settlement, Settlement)
    assert (settlement.price, settlement.settlement_date) == (111.5, "20261109")


def test_history_and_search_requests_are_allowed_reads() -> None:
    assert codec.TIME_BAR_REPLAY in codec.ALLOWED_OUTBOUND
    assert codec.SEARCH_SYMBOLS in codec.ALLOWED_OUTBOUND
    codec.minute_bars_request("ESZ6", "CME", 0, 60)
    codec.search_options_request("S&P 500", "CME")
