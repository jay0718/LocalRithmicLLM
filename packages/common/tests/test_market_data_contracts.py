import inspect

import pytest
from lrl_common.events import (
    OpenInterest,
    Quote,
    SequenceCounter,
    Settlement,
    Trade,
    decode_event,
    encode_event,
    idempotency_key,
)
from lrl_common.sources import MarketDataSource
from lrl_common.topics import ALL_TOPICS, MARKET_EVENTS, partition_key
from pydantic import ValidationError

BASE = {"source": "replay", "symbol": "ESZ6 C7600", "exchange": "CME", "exchange_ts_ns": 10, "seq": 1}


@pytest.mark.parametrize(
    "event",
    [
        Trade(**BASE, price=12.5, size=3),
        Quote(**BASE, bid_price=12.25, bid_size=2, ask_price=None, ask_size=None),
        OpenInterest(**BASE, open_interest=450),
        Settlement(**BASE, price=111.5, settlement_date="20261109"),
    ],
)
def test_events_round_trip(event) -> None:
    assert decode_event(encode_event(event)) == event


@pytest.mark.parametrize(
    "payload",
    [
        b'{"type": "trade"}',
        b"not json",
        b'{"type": "unknown", "source": "a"}',
        encode_event(Trade(**BASE, price=1, size=1)).replace(b'"schema_version":1', b'"schema_version":2'),
    ],
)
def test_bad_payloads_raise(payload: bytes) -> None:
    with pytest.raises(ValidationError):
        decode_event(payload)


def test_events_are_immutable() -> None:
    with pytest.raises(ValidationError):
        Trade(**BASE, price=1, size=1).price = 2


def test_key_ignores_payload() -> None:
    assert idempotency_key(Trade(**BASE, price=1, size=1)) == idempotency_key(Trade(**BASE, price=2, size=9))


@pytest.mark.parametrize(
    "change", [{"source": "rithmic"}, {"symbol": "ESZ6 P7600"}, {"exchange_ts_ns": 11}, {"seq": 2}]
)
def test_key_changes_with_each_field(change: dict) -> None:
    assert idempotency_key(Trade(**BASE, price=1, size=1)) != idempotency_key(
        Trade(**{**BASE, **change}, price=1, size=1)
    )


def test_key_has_no_delimiter_collisions() -> None:
    first = Trade(**{**BASE, "source": "ab", "symbol": "c"}, price=1, size=1)
    second = Trade(**{**BASE, "source": "a", "symbol": "bc"}, price=1, size=1)
    assert idempotency_key(first) != idempotency_key(second)


def test_sequence_makes_mixed_types_unique() -> None:
    counter = SequenceCounter()
    common = {"source": "s", "symbol": "ES", "exchange": "CME", "exchange_ts_ns": 5}
    trade = Trade(**common, seq=counter.next("ES"), price=1, size=1)
    quote = Quote(**common, seq=counter.next("ES"))
    assert idempotency_key(trade) != idempotency_key(quote)


def test_sequence_is_per_symbol() -> None:
    counter = SequenceCounter(start=7)
    assert [counter.next("A"), counter.next("A"), counter.next("B")] == [7, 8, 7]


def test_clock_sequences_survive_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.time_ns", lambda: 1_000_000_000_000)
    first = SequenceCounter.from_clock()
    last_before_restart = max(first.next("ES") for _ in range(100_000))
    monkeypatch.setattr("time.time_ns", lambda: 1_001_000_000_000)
    assert SequenceCounter.from_clock().next("ES") > last_before_restart


def test_source_interface_is_specified() -> None:
    names = {name for name, _ in inspect.getmembers(MarketDataSource, inspect.isfunction)}
    assert {"connect", "subscribe", "stream", "close"} <= names


def test_partition_key_keeps_a_symbol_together() -> None:
    assert partition_key(Trade(**BASE, price=1, size=1)) == partition_key(OpenInterest(**BASE, open_interest=1))
    assert partition_key(Trade(**BASE, price=1, size=1)) == b"ESZ6 C7600"


def test_retention_fits_the_pi_disk() -> None:
    assert MARKET_EVENTS.max_disk_bytes == 15 * 1024**3
    assert sum(topic.max_disk_bytes for topic in ALL_TOPICS) < 20 * 1024**3
