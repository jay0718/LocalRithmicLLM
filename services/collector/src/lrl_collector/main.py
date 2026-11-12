"""Collect live market data from Rithmic and publish it to Redpanda.

Run with: python -m lrl_collector.main --symbols ESZ6 "ESZ6 C7600"
"""

import argparse
import asyncio
import logging
import os
import signal

from prometheus_client import start_http_server

from .metrics import build_registry
from .publisher import create_producer, publish
from .rithmic.codec import Credentials
from .rithmic.source import RithmicSource

log = logging.getLogger("lrl_collector")


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise SystemExit(f"Set {name}")
    return value


async def run(symbols: list[str], exchange: str, max_events: int | None) -> None:
    credentials = Credentials(
        user=env("RITHMIC_USER"),
        password=env("RITHMIC_PASSWORD"),
        system_name=env("RITHMIC_SYSTEM_NAME"),
        app_name=env("RITHMIC_APP_NAME"),
        app_version=env("RITHMIC_APP_VERSION", "0.1.0"),
    )
    source = RithmicSource(env("RITHMIC_URI"), credentials, exchange=exchange)
    registry, published, publish_failed = build_registry(source)
    start_http_server(int(env("COLLECTOR_METRICS_PORT", "9101")), registry=registry)

    producer = create_producer(env("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"))
    await producer.start()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    try:
        await source.subscribe(symbols)
        await source.connect()
        count = 0
        async for event in source.stream():
            try:
                await publish(producer, event)
                published.inc()
            except Exception:
                publish_failed()
                log.exception("Publish failed")
            count += 1
            if stop.is_set() or (max_events and count >= max_events):
                break
    finally:
        await source.close()
        await producer.stop()
        log.info("Stopped; dropped %d events", source.dropped)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--exchange", default="CME")
    parser.add_argument("--max-events", type=int, help="stop after this many events, for testing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run(args.symbols, args.exchange, args.max_events))


if __name__ == "__main__":
    main()
