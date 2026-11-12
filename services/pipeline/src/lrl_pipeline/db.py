"""Schema migrations, partitions, inserts and retention for market events."""

import re
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from importlib import resources

import asyncpg
from lrl_common.events import OpenInterest, Quote, Settlement, Trade, idempotency_key

MarketEvent = Trade | Quote | OpenInterest | Settlement
_PARTITION = re.compile(r"^md_events_(\d{8})$")

_INSERT = """
INSERT INTO md_events (ts, event_key, type, source, symbol, exchange, exchange_ts_ns, seq,
                       price, size, bid_price, bid_size, ask_price, ask_size, open_interest, settlement_date)
SELECT * FROM unnest($1::timestamptz[], $2::uuid[], $3::text[], $4::text[], $5::text[], $6::text[],
                     $7::bigint[], $8::bigint[], $9::float8[], $10::bigint[], $11::float8[], $12::bigint[],
                     $13::float8[], $14::bigint[], $15::bigint[], $16::date[])
ON CONFLICT DO NOTHING
"""


async def migrate(conn: asyncpg.Connection) -> int:
    """Apply pending migrations in order under an advisory lock. Returns the schema version."""
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext('lrl_migrations'))")
        await conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version int PRIMARY KEY)")
        applied = {row["version"] for row in await conn.fetch("SELECT version FROM schema_migrations")}
        files = sorted(f for f in resources.files("lrl_pipeline.migrations").iterdir() if f.name.endswith(".sql"))
        for file in files:
            version = int(file.name.split("_", 1)[0])
            if version not in applied:
                await conn.execute(file.read_text())
                await conn.execute("INSERT INTO schema_migrations VALUES ($1)", version)
                applied.add(version)
    return max(applied, default=0)


def event_ts(event: MarketEvent) -> datetime:
    return datetime.fromtimestamp(event.exchange_ts_ns / 1e9, UTC)


def to_row(event: MarketEvent) -> tuple:
    is_trade, is_quote = isinstance(event, Trade), isinstance(event, Quote)
    is_settlement = isinstance(event, Settlement)
    return (
        event_ts(event),
        uuid.UUID(idempotency_key(event)),
        event.type,
        event.source,
        event.symbol,
        event.exchange,
        event.exchange_ts_ns,
        event.seq,
        event.price if is_trade or is_settlement else None,
        event.size if is_trade else None,
        event.bid_price if is_quote else None,
        event.bid_size if is_quote else None,
        event.ask_price if is_quote else None,
        event.ask_size if is_quote else None,
        event.open_interest if isinstance(event, OpenInterest) else None,
        datetime.strptime(event.settlement_date, "%Y%m%d").date() if is_settlement else None,
    )


async def insert_events(conn: asyncpg.Connection, events: Sequence[MarketEvent]) -> int:
    """Insert events, ignoring ones already stored. Returns how many were new."""
    if not events:
        return 0
    columns = list(zip(*(to_row(event) for event in events), strict=True))
    status = await conn.execute(_INSERT, *columns)
    return int(status.split()[-1])


def partition_name(day: date) -> str:
    return f"md_events_{day:%Y%m%d}"


async def ensure_partitions(conn: asyncpg.Connection, days: Iterable[date]) -> list[str]:
    """Create daily partitions that don't exist yet. Returns the names created."""
    existing = set(await list_partitions(conn))
    created = []
    for day in sorted(set(days)):
        name = partition_name(day)
        if name in existing:
            continue
        start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        await conn.execute(
            f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF md_events "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{(start + timedelta(days=1)).isoformat()}')"
        )
        created.append(name)
    return created


async def list_partitions(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
        "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'md_events'"
    )
    return sorted(row["relname"] for row in rows if _PARTITION.match(row["relname"]))


async def apply_retention(conn: asyncpg.Connection, keep_days: int, max_bytes: int, today: date) -> list[str]:
    """Drop daily partitions older than keep_days, then the oldest ones until under max_bytes.

    Never drops today's partition or the default partition.
    """
    dropped = []
    cutoff = today - timedelta(days=keep_days)
    partitions = await list_partitions(conn)
    for name in partitions:
        day = datetime.strptime(_PARTITION.match(name).group(1), "%Y%m%d").date()
        if day < cutoff:
            await conn.execute(f"DROP TABLE {name}")
            dropped.append(name)
    remaining = [name for name in partitions if name not in dropped and name < partition_name(today)]
    while remaining and await total_bytes(conn) > max_bytes:
        name = remaining.pop(0)
        await conn.execute(f"DROP TABLE {name}")
        dropped.append(name)
    return dropped


async def total_bytes(conn: asyncpg.Connection) -> int:
    """Disk used by every md_events partition, including the default one and indexes."""
    return await conn.fetchval(
        "SELECT coalesce(sum(pg_total_relation_size(i.inhrelid)), 0) FROM pg_inherits i "
        "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'md_events'"
    )
