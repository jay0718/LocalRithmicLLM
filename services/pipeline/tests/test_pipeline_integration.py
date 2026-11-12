"""The writer against the real Postgres and Redpanda from compose.yaml."""

import asyncio
import os
import uuid
from datetime import UTC, date, datetime, timedelta

import asyncpg
import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from lrl_collector.replay import FaultConfig, inject_faults
from lrl_collector.synthetic import MarketConfig, SyntheticMarket
from lrl_common.events import Trade, encode_event, idempotency_key
from lrl_pipeline import db
from lrl_pipeline.reprocess import reprocess
from lrl_pipeline.writer import PostgresSink, Writer, create_consumer, create_dlq_producer

pytestmark = pytest.mark.integration
BOOTSTRAP = "localhost:19092"
ADMIN_DSN = f"postgresql://lrl:{os.environ.get('POSTGRES_PASSWORD', '')}@localhost:15432/lrl"


@pytest.fixture
async def dsn():
    name = f"lrl_test_{uuid.uuid4().hex[:10]}"
    admin = await asyncpg.connect(ADMIN_DSN)
    await admin.execute(f"CREATE DATABASE {name}")
    url = ADMIN_DSN.rsplit("/", 1)[0] + f"/{name}"
    conn = await asyncpg.connect(url)
    await db.migrate(conn)
    await conn.close()
    yield url
    await admin.execute(f"DROP DATABASE {name} WITH (FORCE)")
    await admin.close()


@pytest.fixture
async def topics():
    suffix = uuid.uuid4().hex[:8]
    yield f"test.events.{suffix}", f"test.dlq.{suffix}"


async def produce(topic: str, values: list[bytes]) -> None:
    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    try:
        for value in values:
            await producer.send(topic, value=value, key=b"k")
        await producer.flush()
    finally:
        await producer.stop()


async def drain(dsn: str, topic: str, dlq: str, group: str, expected: int, **kwargs) -> Writer:
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    consumer = create_consumer(BOOTSTRAP, topic, group)
    producer = create_dlq_producer(BOOTSTRAP)
    writer = Writer(consumer, producer, dlq, PostgresSink(pool), flush_interval_ms=200, **kwargs)
    await consumer.start()
    await producer.start()
    try:
        async with asyncio.timeout(30):
            consumed = 0
            while consumed < expected:
                consumed += await writer.run_once()
    finally:
        await consumer.stop()
        await producer.stop()
        await pool.close()
    return writer


async def committed(topic: str, group: str) -> int:
    consumer = AIOKafkaConsumer(bootstrap_servers=BOOTSTRAP, group_id=group, enable_auto_commit=False)
    await consumer.start()
    try:
        return await consumer.committed(TopicPartition(topic, 0)) or 0
    finally:
        await consumer.stop()


async def dlq_values(topic: str) -> list[bytes]:
    consumer = AIOKafkaConsumer(bootstrap_servers=BOOTSTRAP, enable_auto_commit=False)
    await consumer.start()
    try:
        tp = TopicPartition(topic, 0)
        consumer.assign([tp])
        end = (await consumer.end_offsets([tp]))[tp]
        consumer.seek(tp, 0)
        values = []
        while len(values) < end:
            for records in (await consumer.getmany(timeout_ms=500)).values():
                values += [r.value for r in records]
        return values
    finally:
        await consumer.stop()


async def count_rows(dsn: str, where: str = "true") -> int:
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetchval(f"SELECT count(*) FROM md_events WHERE {where}")
    finally:
        await conn.close()


async def test_migrations_are_idempotent(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    assert await db.migrate(conn) == 2
    assert await db.migrate(conn) == 2
    await conn.close()


async def test_replayed_topic_with_duplicates_stores_each_event_once(dsn, topics) -> None:
    topic, dlq = topics
    events = list(SyntheticMarket(MarketConfig(strikes_each_side=3, expiry_days=(30,))).events(300))
    noisy = list(inject_faults(events, FaultConfig(duplicate=0.2, reorder=0.1, seed=5)))
    await produce(topic, [encode_event(e) for e in noisy])
    writer = await drain(dsn, topic, dlq, "g1", len(noisy))
    assert await count_rows(dsn) == len(events)
    assert writer.stats.written == len(events)
    assert writer.stats.duplicates == len(noisy) - len(events)
    assert await committed(topic, "g1") == len(noisy)

    # A second consumer group replaying the whole topic adds nothing.
    again = await drain(dsn, topic, dlq, "g2", len(noisy))
    assert (again.stats.written, await count_rows(dsn)) == (0, len(events))


async def test_rows_land_in_daily_partitions(dsn, topics) -> None:
    topic, dlq = topics
    await produce(topic, [encode_event(e) for e in SyntheticMarket(MarketConfig(strikes_each_side=1)).events(10)])
    await drain(dsn, topic, dlq, "g", 1)
    conn = await asyncpg.connect(dsn)
    assert await conn.fetchval("SELECT count(*) FROM md_events_default") == 0
    assert await conn.fetchval("SELECT count(*) FROM md_events_20261109") > 0
    await conn.close()


async def test_poison_and_bad_rows_are_dead_lettered(dsn, topics) -> None:
    topic, dlq = topics
    overflow = Trade(
        source="t", symbol="ES", exchange="CME", exchange_ts_ns=1_800_000_000_000_000_000, seq=1, price=1, size=2**70
    )
    good = Trade(
        source="t", symbol="ES", exchange="CME", exchange_ts_ns=1_800_000_000_000_000_001, seq=2, price=1, size=1
    )
    values = [b"{not json", encode_event(overflow), encode_event(good)]
    await produce(topic, values)
    writer = await drain(dsn, topic, dlq, "g", 3)
    assert await count_rows(dsn) == 1
    assert writer.stats.dead_letter_reasons == {"decode_error": 1, "insert_error": 1}
    assert sorted(await dlq_values(dlq)) == sorted(values[:2])
    assert await committed(topic, "g") == 3


async def test_crash_before_commit_replays_without_loss_or_duplicates(dsn, topics) -> None:
    topic, dlq = topics
    events = list(SyntheticMarket(MarketConfig(strikes_each_side=1, expiry_days=(30,))).events(50))
    await produce(topic, [encode_event(e) for e in events])

    async def crash() -> None:
        raise RuntimeError("simulated crash after write, before commit")

    with pytest.raises(RuntimeError):
        await drain(dsn, topic, dlq, "g", len(events), before_commit=crash)
    assert await committed(topic, "g") == 0
    stored_before_restart = await count_rows(dsn)
    assert stored_before_restart > 0

    restarted = await drain(dsn, topic, dlq, "g", len(events))
    assert await count_rows(dsn) == len(events)
    assert restarted.stats.duplicates >= stored_before_restart


async def test_reprocess_inserts_fixed_events_and_is_repeatable(dsn, topics) -> None:
    _, dlq = topics
    event = Trade(
        source="t", symbol="ES", exchange="CME", exchange_ts_ns=1_800_000_000_000_000_000, seq=7, price=1, size=1
    )
    await produce(dlq, [encode_event(event), b"still broken"])
    first = await reprocess(BOOTSTRAP, dsn, dlq)
    assert (first.read, first.inserted, first.still_failing) == (2, 1, 1)
    second = await reprocess(BOOTSTRAP, dsn, dlq)
    assert (second.inserted, second.already_stored, second.still_failing) == (0, 1, 1)
    conn = await asyncpg.connect(dsn)
    key = await conn.fetchval("SELECT event_key FROM md_events")
    await conn.close()
    assert key.hex == idempotency_key(event)


async def test_retention_drops_old_and_oversized_partitions(dsn) -> None:
    today = date(2026, 11, 11)
    conn = await asyncpg.connect(dsn)
    days = [today - timedelta(days=n) for n in (40, 31, 5, 2, 0)]
    await db.ensure_partitions(conn, days)
    for day in days:
        ts = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
        event = Trade(
            source="t", symbol="ES", exchange="CME", exchange_ts_ns=int(ts.timestamp() * 1e9), seq=0, price=1, size=1
        )
        await db.insert_events(conn, [event])

    dropped = await db.apply_retention(conn, keep_days=30, max_bytes=10**12, today=today)
    assert dropped == [db.partition_name(today - timedelta(days=40)), db.partition_name(today - timedelta(days=31))]

    dropped = await db.apply_retention(conn, keep_days=30, max_bytes=0, today=today)
    assert dropped == [db.partition_name(today - timedelta(days=5)), db.partition_name(today - timedelta(days=2))]
    assert await db.list_partitions(conn) == [db.partition_name(today)]
    await conn.close()


async def test_settlements_are_stored(dsn: str) -> None:
    from lrl_common.events import Settlement

    conn = await asyncpg.connect(dsn)
    event = Settlement(
        source="t",
        symbol="ESZ6 C7650",
        exchange="CME",
        exchange_ts_ns=1_800_000_000_000_000_000,
        seq=1,
        price=111.5,
        settlement_date="20261109",
    )
    await db.ensure_partitions(conn, {db.event_ts(event).date()})
    assert await db.insert_events(conn, [event]) == 1
    row = await conn.fetchrow("SELECT type, price, settlement_date FROM md_events")
    await conn.close()
    assert (row["type"], row["price"], str(row["settlement_date"])) == ("settlement", 111.5, "2026-11-09")
