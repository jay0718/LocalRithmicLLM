"""Consume market events and write them to Postgres in batches.

Offsets are committed only after a batch is stored or dead-lettered, so a crash
replays the batch, and idempotent inserts make that replay harmless.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import asyncpg
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, ConsumerRecord, TopicPartition
from lrl_common.events import OpenInterest, Quote, Settlement, Trade, decode_event

from . import db

log = logging.getLogger(__name__)
MarketEvent = Trade | Quote | OpenInterest | Settlement

_UNAVAILABLE = (
    OSError,
    TimeoutError,
    asyncpg.PostgresConnectionError,
    asyncpg.CannotConnectNowError,
    asyncpg.TooManyConnectionsError,
)


def is_transient(error: BaseException) -> bool:
    """True when the database is unavailable rather than the data being bad. Transient errors retry forever.

    asyncpg reports values it can't encode as an InterfaceError that is also a
    ValueError, so those count as bad data, not an outage.
    """
    if isinstance(error, ValueError):
        return False
    return isinstance(error, (*_UNAVAILABLE, asyncpg.InterfaceError))


class Sink(Protocol):
    async def ensure_days(self, days: set[date]) -> None: ...

    async def insert(self, events: Sequence[MarketEvent]) -> int: ...


class PostgresSink:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._known_days: set[date] = set()

    async def ensure_days(self, days: set[date]) -> None:
        missing = days - self._known_days
        if missing:
            async with self._pool.acquire() as conn:
                await db.ensure_partitions(conn, missing)
            self._known_days |= missing

    async def insert(self, events: Sequence[MarketEvent]) -> int:
        async with self._pool.acquire() as conn:
            return await db.insert_events(conn, events)


@dataclass
class WriterStats:
    batches: int = 0
    written: int = 0
    duplicates: int = 0
    dead_lettered: int = 0
    retries: int = 0
    last_batch_seconds: float = 0.0
    dead_letter_reasons: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DeadLetter:
    record: ConsumerRecord
    reason: str
    detail: str


class Writer:
    def __init__(
        self,
        consumer: AIOKafkaConsumer,
        dlq_producer: AIOKafkaProducer,
        dlq_topic: str,
        sink: Sink,
        batch_size: int = 2000,
        flush_interval_ms: int = 500,
        retry_cap_seconds: float = 30.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        before_commit: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._consumer = consumer
        self._dlq_producer = dlq_producer
        self._dlq_topic = dlq_topic
        self._sink = sink
        self._batch_size = batch_size
        self._flush_interval_ms = flush_interval_ms
        self._retry_cap = retry_cap_seconds
        self._sleep = sleep
        self._before_commit = before_commit
        self.stats = WriterStats()

    async def run_once(self) -> int:
        """Process one batch. Returns the number of records consumed."""
        batches = await self._consumer.getmany(timeout_ms=self._flush_interval_ms, max_records=self._batch_size)
        records = [record for partition_records in batches.values() for record in partition_records]
        if not records:
            return 0
        started = time.monotonic()
        events, dead = self._decode(records)
        stored, rejected = await self._store(events)
        dead += rejected
        await self._dead_letter(dead)
        if self._before_commit:
            await self._before_commit()
        await self._consumer.commit({tp: recs[-1].offset + 1 for tp, recs in batches.items() if recs})
        self.stats.batches += 1
        self.stats.written += stored
        self.stats.duplicates += len(events) - len(rejected) - stored
        self.stats.last_batch_seconds = time.monotonic() - started
        return len(records)

    def _decode(self, records: list[ConsumerRecord]) -> tuple[list[tuple[ConsumerRecord, MarketEvent]], list]:
        events, dead = [], []
        for record in records:
            try:
                events.append((record, decode_event(record.value)))
            except Exception as error:  # any payload we can't parse is poison, whatever the cause
                dead.append(DeadLetter(record, "decode_error", str(error)[:500]))
        return events, dead

    async def _with_retry(self, operation: Callable[[], Awaitable[int | None]]):
        delay = 0.5
        while True:
            try:
                return await operation()
            except Exception as error:
                if not is_transient(error):
                    raise
                self.stats.retries += 1
                log.warning("Database unavailable (%s); retrying in %.1fs", type(error).__name__, delay)
                await self._sleep(delay)
                delay = min(delay * 2, self._retry_cap)

    async def _store(self, pairs: list[tuple[ConsumerRecord, MarketEvent]]) -> tuple[int, list[DeadLetter]]:
        if not pairs:
            return 0, []
        events = [event for _, event in pairs]
        await self._with_retry(lambda: self._sink.ensure_days({db.event_ts(e).date() for e in events}))
        try:
            return await self._with_retry(lambda: self._sink.insert(events)), []
        except (asyncpg.PostgresError, asyncpg.InterfaceError, ValueError, OverflowError) as error:
            log.warning("Batch insert failed (%s); retrying row by row", type(error).__name__)
        stored, dead = 0, []
        for record, event in pairs:
            try:
                stored += await self._with_retry(lambda event=event: self._sink.insert([event]))
            except (asyncpg.PostgresError, asyncpg.InterfaceError, ValueError, OverflowError) as error:
                dead.append(DeadLetter(record, "insert_error", f"{type(error).__name__}: {error}"[:500]))
        return stored, dead

    async def _dead_letter(self, dead: list[DeadLetter]) -> None:
        for item in dead:
            record = item.record
            headers = [
                ("reason", item.reason.encode()),
                ("detail", item.detail.encode()),
                ("source_topic", record.topic.encode()),
                ("source_partition", str(record.partition).encode()),
                ("source_offset", str(record.offset).encode()),
            ]
            await self._dlq_producer.send(self._dlq_topic, value=record.value, key=record.key, headers=headers)
            self.stats.dead_letter_reasons[item.reason] = self.stats.dead_letter_reasons.get(item.reason, 0) + 1
        if dead:
            # The DLQ must be durable before the source offsets move past these records.
            await self._dlq_producer.flush()
            self.stats.dead_lettered += len(dead)


def create_consumer(bootstrap_servers: str, topic: str, group_id: str) -> AIOKafkaConsumer:
    return AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )


def create_dlq_producer(bootstrap_servers: str) -> AIOKafkaProducer:
    return AIOKafkaProducer(bootstrap_servers=bootstrap_servers, enable_idempotence=True, acks="all")


async def consumer_lag(consumer: AIOKafkaConsumer) -> int:
    partitions: list[TopicPartition] = list(consumer.assignment())
    if not partitions:
        return 0
    ends = await consumer.end_offsets(partitions)
    lag = 0
    for tp in partitions:
        lag += max(ends[tp] - await consumer.position(tp), 0)
    return lag
