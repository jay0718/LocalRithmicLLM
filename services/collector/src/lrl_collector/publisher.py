"""Publish normalized events to Redpanda."""

from aiokafka import AIOKafkaProducer
from lrl_common.events import OpenInterest, Quote, Trade, encode_event
from lrl_common.topics import MARKET_EVENTS, partition_key


def create_producer(bootstrap_servers: str) -> AIOKafkaProducer:
    # Idempotence makes producer retries safe: a resend after a timeout is not written twice.
    return AIOKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        enable_idempotence=True,
        acks="all",
        linger_ms=5,
        compression_type="lz4",
    )


async def publish(producer: AIOKafkaProducer, event: Trade | Quote | OpenInterest) -> None:
    await producer.send(MARKET_EVENTS.name, value=encode_event(event), key=partition_key(event))
