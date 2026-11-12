"""Redpanda topic definitions.

All event types share one topic keyed by symbol. A topic per type would lose the
ordering between a contract's quotes and open interest.
"""

from dataclasses import dataclass

from .events import OpenInterest, Quote, Trade

_DAY_MS = 86_400_000
_GIB = 1024**3


@dataclass(frozen=True)
class TopicSpec:
    name: str
    partitions: int
    retention_ms: int
    retention_bytes_per_partition: int

    @property
    def max_disk_bytes(self) -> int:
        return self.partitions * self.retention_bytes_per_partition


MARKET_EVENTS = TopicSpec(
    "md.events.v1", partitions=3, retention_ms=2 * _DAY_MS, retention_bytes_per_partition=5 * _GIB
)
MARKET_EVENTS_DLQ = TopicSpec(
    "md.events.dlq.v1", partitions=1, retention_ms=14 * _DAY_MS, retention_bytes_per_partition=_GIB
)
ALL_TOPICS = (MARKET_EVENTS, MARKET_EVENTS_DLQ)


def partition_key(event: Trade | Quote | OpenInterest) -> bytes:
    return event.symbol.encode()
