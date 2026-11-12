"""Writer logic with fake Kafka and database objects."""

from collections import namedtuple

import asyncpg
import pytest
from lrl_common.events import Trade, encode_event
from lrl_pipeline.writer import Writer, consumer_lag, is_transient

TP = namedtuple("TP", "topic partition")
Record = namedtuple("Record", "topic partition offset key value")


def trade(seq: int, size: int = 1) -> Trade:
    return Trade(
        source="t",
        symbol="ES",
        exchange="CME",
        exchange_ts_ns=1_800_000_000_000_000_000 + seq,
        seq=seq,
        price=1,
        size=size,
    )


class FakeConsumer:
    def __init__(self, values: list[bytes]) -> None:
        self.tp = TP("md", 0)
        self.batches = [{self.tp: [Record("md", 0, i, b"ES", v) for i, v in enumerate(values)]}]
        self.commits: list[dict] = []

    async def getmany(self, timeout_ms: int, max_records: int):
        return self.batches.pop(0) if self.batches else {}

    async def commit(self, offsets: dict) -> None:
        self.commits.append(offsets)


class FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes, list]] = []
        self.flushes = 0

    async def send(self, topic: str, value: bytes, key: bytes, headers: list) -> None:
        self.sent.append((topic, value, dict(headers)))

    async def flush(self) -> None:
        self.flushes += 1


class FakeSink:
    def __init__(self, failures: list[BaseException] | None = None, bad_sizes: frozenset[int] = frozenset()) -> None:
        self.failures = list(failures or [])
        self.bad_sizes = bad_sizes
        self.stored: dict[int, Trade] = {}
        self.days: set = set()

    async def ensure_days(self, days) -> None:
        self.days |= days

    async def insert(self, events) -> int:
        if self.failures:
            raise self.failures.pop(0)
        if any(e.size in self.bad_sizes for e in events):
            raise asyncpg.NumericValueOutOfRangeError("out of range")
        before = len(self.stored)
        self.stored.update({e.seq: e for e in events if e.seq not in self.stored})
        return len(self.stored) - before


def writer_for(values: list[bytes], sink: FakeSink, **kwargs):
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    consumer, producer = FakeConsumer(values), FakeProducer()
    writer = Writer(consumer, producer, "md.dlq", sink, sleep=sleep, **kwargs)
    return writer, consumer, producer, sleeps


async def test_stores_batch_and_commits_next_offset() -> None:
    sink = FakeSink()
    writer, consumer, producer, _ = writer_for([encode_event(trade(i)) for i in range(3)], sink)
    assert await writer.run_once() == 3
    assert sorted(sink.stored) == [0, 1, 2]
    assert consumer.commits == [{consumer.tp: 3}]
    assert producer.sent == []
    assert (writer.stats.written, writer.stats.duplicates) == (3, 0)


async def test_duplicates_are_counted_not_stored_twice() -> None:
    sink = FakeSink()
    writer, *_ = writer_for([encode_event(trade(1)), encode_event(trade(1))], sink)
    await writer.run_once()
    assert (writer.stats.written, writer.stats.duplicates) == (1, 1)


async def test_poison_messages_go_to_dlq_with_context() -> None:
    sink = FakeSink()
    writer, consumer, producer, _ = writer_for([b"not json", encode_event(trade(1))], sink)
    await writer.run_once()
    assert list(sink.stored) == [1]
    ((topic, value, headers),) = producer.sent
    assert (topic, value) == ("md.dlq", b"not json")
    assert headers["reason"] == b"decode_error"
    assert (headers["source_topic"], headers["source_partition"], headers["source_offset"]) == (b"md", b"0", b"0")
    assert producer.flushes == 1
    assert consumer.commits == [{consumer.tp: 2}]


async def test_bad_row_is_isolated_and_dead_lettered() -> None:
    sink = FakeSink(bad_sizes=frozenset({99}))
    writer, consumer, producer, _ = writer_for([encode_event(trade(i, 99 if i == 1 else 1)) for i in range(3)], sink)
    await writer.run_once()
    assert sorted(sink.stored) == [0, 2]
    assert [headers["reason"] for _, _, headers in producer.sent] == [b"insert_error"]
    assert consumer.commits == [{consumer.tp: 3}]


async def test_database_outage_retries_with_backoff_and_loses_nothing() -> None:
    sink = FakeSink(failures=[ConnectionRefusedError()] * 4)
    writer, consumer, producer, sleeps = writer_for([encode_event(trade(1))], sink, retry_cap_seconds=2)
    await writer.run_once()
    assert sleeps == [0.5, 1.0, 2.0, 2.0]
    assert list(sink.stored) == [1] and producer.sent == []
    assert writer.stats.retries == 4


async def test_crash_before_commit_leaves_offsets_unchanged() -> None:
    async def crash() -> None:
        raise RuntimeError("crash")

    sink = FakeSink()
    writer, consumer, *_ = writer_for([encode_event(trade(1))], sink, before_commit=crash)
    with pytest.raises(RuntimeError):
        await writer.run_once()
    assert consumer.commits == []


async def test_empty_poll_does_nothing() -> None:
    writer, consumer, *_ = writer_for([], FakeSink())
    consumer.batches = []
    assert await writer.run_once() == 0
    assert consumer.commits == []


@pytest.mark.parametrize(
    ("error", "transient"),
    [
        (ConnectionRefusedError(), True),
        (TimeoutError(), True),
        (asyncpg.CannotConnectNowError("starting"), True),
        (asyncpg.InterfaceError("connection is closed"), True),
        (asyncpg.NumericValueOutOfRangeError("x"), False),
        (asyncpg.exceptions._base.DataError("invalid input for query argument"), False),
        (ValueError("x"), False),
    ],
)
def test_error_classification(error: BaseException, transient: bool) -> None:
    assert is_transient(error) is transient


class LagConsumer:
    def __init__(self, ends: dict, positions: dict) -> None:
        self.ends, self.positions = ends, positions

    def assignment(self) -> set:
        return set(self.ends)

    async def end_offsets(self, partitions) -> dict:
        return self.ends

    async def position(self, tp) -> int:
        return self.positions[tp]


async def test_consumer_lag_sums_partitions() -> None:
    a, b = TP("md", 0), TP("md", 1)
    assert await consumer_lag(LagConsumer({a: 10, b: 5}, {a: 4, b: 5})) == 6
    assert await consumer_lag(LagConsumer({}, {})) == 0
