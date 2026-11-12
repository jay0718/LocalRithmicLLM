import asyncio
import uuid

import pytest
from aiokafka import AIOKafkaConsumer, TopicPartition
from lrl_collector.publisher import create_producer, publish
from lrl_common.events import Quote, Trade, decode_event
from lrl_common.topics import MARKET_EVENTS

pytestmark = pytest.mark.integration
BOOTSTRAP = "localhost:19092"


async def test_published_events_round_trip_by_symbol_partition() -> None:
    symbol = f"TEST-{uuid.uuid4().hex[:8]}"
    events = [
        Trade(source="t", symbol=symbol, exchange="CME", exchange_ts_ns=1, seq=0, price=1.5, size=2),
        Quote(source="t", symbol=symbol, exchange="CME", exchange_ts_ns=2, seq=1, bid_price=1, ask_price=2),
    ]
    consumer = AIOKafkaConsumer(bootstrap_servers=BOOTSTRAP, enable_auto_commit=False)
    await consumer.start()
    partitions = [TopicPartition(MARKET_EVENTS.name, p) for p in range(MARKET_EVENTS.partitions)]
    consumer.assign(partitions)
    ends = await consumer.end_offsets(partitions)
    for partition, offset in ends.items():
        consumer.seek(partition, offset)

    producer = create_producer(BOOTSTRAP)
    try:
        await producer.start()
        for event in events:
            await publish(producer, event)
        await producer.flush()
        received = []
        async with asyncio.timeout(10):
            while len(received) < 2:
                for partition, records in (await consumer.getmany(timeout_ms=500)).items():
                    received += [
                        (partition.partition, decode_event(r.value)) for r in records if r.key == symbol.encode()
                    ]
    finally:
        await producer.stop()
        await consumer.stop()
    assert [event for _, event in received] == events
    assert len({partition for partition, _ in received}) == 1
