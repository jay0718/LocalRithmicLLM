"""Run the market data writer.

Run with: python -m lrl_pipeline.main
"""

import asyncio
import logging
import os
import signal
from datetime import UTC, datetime, timedelta

import asyncpg
from lrl_common.topics import MARKET_EVENTS, MARKET_EVENTS_DLQ
from prometheus_client import CollectorRegistry, start_http_server
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector

from . import db
from .writer import PostgresSink, Writer, consumer_lag, create_consumer, create_dlq_producer

log = logging.getLogger("lrl_pipeline")
MAINTENANCE_INTERVAL_SECONDS = 3600


class WriterMetrics(Collector):
    def __init__(self, writer: Writer) -> None:
        self._writer = writer
        self.lag = 0

    def collect(self):
        stats = self._writer.stats
        yield CounterMetricFamily("lrl_writer_written", "Events stored", value=stats.written)
        yield CounterMetricFamily("lrl_writer_duplicates", "Events already stored", value=stats.duplicates)
        yield CounterMetricFamily("lrl_writer_retries", "Database retries", value=stats.retries)
        yield CounterMetricFamily("lrl_writer_batches", "Batches committed", value=stats.batches)
        dead = CounterMetricFamily("lrl_writer_dead_lettered", "Events sent to the DLQ", labels=["reason"])
        for reason, count in sorted(stats.dead_letter_reasons.items()):
            dead.add_metric([reason], count)
        yield dead
        yield GaugeMetricFamily("lrl_writer_batch_seconds", "Last batch duration", value=stats.last_batch_seconds)
        yield GaugeMetricFamily("lrl_writer_consumer_lag", "Records not yet consumed", value=self.lag)


async def maintain(pool: asyncpg.Pool, keep_days: int, max_bytes: int) -> None:
    today = datetime.now(UTC).date()
    async with pool.acquire() as conn:
        await db.ensure_partitions(conn, {today + timedelta(days=offset) for offset in range(3)})
        dropped = await db.apply_retention(conn, keep_days, max_bytes, today)
    if dropped:
        log.info("Retention dropped %s", ", ".join(dropped))


async def run() -> None:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
    keep_days = int(os.environ.get("WRITER_KEEP_DAYS", "30"))
    max_bytes = int(float(os.environ.get("WRITER_MAX_GB", "20")) * 1024**3)
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=4)
    async with pool.acquire() as conn:
        await db.migrate(conn)
    await maintain(pool, keep_days, max_bytes)

    consumer = create_consumer(bootstrap, MARKET_EVENTS.name, "lrl-writer")
    producer = create_dlq_producer(bootstrap)
    writer = Writer(consumer, producer, MARKET_EVENTS_DLQ.name, PostgresSink(pool))
    metrics = WriterMetrics(writer)
    registry = CollectorRegistry()
    registry.register(metrics)
    start_http_server(int(os.environ.get("WRITER_METRICS_PORT", "9102")), registry=registry)

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    await consumer.start()
    await producer.start()
    next_maintenance = asyncio.get_running_loop().time() + MAINTENANCE_INTERVAL_SECONDS
    try:
        while not stop.is_set():
            await writer.run_once()
            metrics.lag = await consumer_lag(consumer)
            if asyncio.get_running_loop().time() >= next_maintenance:
                await maintain(pool, keep_days, max_bytes)
                next_maintenance += MAINTENANCE_INTERVAL_SECONDS
    finally:
        await consumer.stop()
        await producer.stop()
        await pool.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
