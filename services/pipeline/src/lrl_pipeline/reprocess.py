"""Replay dead-lettered events into Postgres after a fix.

Reads the DLQ from the start (or --from-offset) up to its current end. Inserts are
idempotent, so this is safe to run any number of times. Events that still fail
stay in the DLQ and are reported.

Run with: python -m lrl_pipeline.reprocess
"""

import argparse
import asyncio
import os
from dataclasses import dataclass

import asyncpg
from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from lrl_common.events import decode_event
from lrl_common.topics import MARKET_EVENTS_DLQ

from . import db


@dataclass
class ReprocessResult:
    read: int = 0
    inserted: int = 0
    already_stored: int = 0
    still_failing: int = 0


async def topic_partitions(bootstrap_servers: str, topic: str) -> list[TopicPartition]:
    """Partitions of a topic. A consumer only knows partitions for topics it subscribes to."""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        (description,) = await admin.describe_topics([topic])
    finally:
        await admin.close()
    if description.get("error_code"):
        return []
    return [TopicPartition(topic, p["partition"]) for p in description["partitions"]]


async def reprocess(bootstrap_servers: str, dsn: str, topic: str, from_offset: int = 0) -> ReprocessResult:
    result = ReprocessResult()
    consumer = AIOKafkaConsumer(bootstrap_servers=bootstrap_servers, enable_auto_commit=False)
    conn = await asyncpg.connect(dsn)
    try:
        partitions = await topic_partitions(bootstrap_servers, topic)
        await consumer.start()
        if not partitions:
            return result
        consumer.assign(partitions)
        ends = await consumer.end_offsets(partitions)
        for tp in partitions:
            consumer.seek(tp, from_offset)
        remaining = {tp for tp in partitions if ends[tp] > from_offset}
        while remaining:
            batches = await consumer.getmany(timeout_ms=1000, max_records=1000)
            for tp, records in batches.items():
                for record in records:
                    if record.offset >= ends[tp]:
                        continue
                    result.read += 1
                    try:
                        event = decode_event(record.value)
                        await db.ensure_partitions(conn, {db.event_ts(event).date()})
                        new = await db.insert_events(conn, [event])
                    except Exception:
                        result.still_failing += 1
                        continue
                    result.inserted += new
                    result.already_stored += 1 - new
            remaining = {tp for tp in remaining if await consumer.position(tp) < ends[tp]}
    finally:
        await consumer.stop()
        await conn.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--topic", default=MARKET_EVENTS_DLQ.name)
    parser.add_argument("--from-offset", type=int, default=0)
    args = parser.parse_args()
    result = asyncio.run(
        reprocess(
            os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"),
            os.environ["DATABASE_URL"],
            args.topic,
            args.from_offset,
        )
    )
    print(
        f"read {result.read}, inserted {result.inserted}, already stored {result.already_stored}, "
        f"still failing {result.still_failing}"
    )


if __name__ == "__main__":
    main()
