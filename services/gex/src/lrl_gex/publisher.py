"""Publish snapshots on a fixed cadence to any number of consumers."""

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

T = TypeVar("T")


class SnapshotHub[T]:
    """Holds the latest snapshot and fans it out.

    Each subscriber has a one-slot queue that keeps only the newest snapshot, so a
    slow client misses intermediate updates and never delays anyone else.
    """

    def __init__(self) -> None:
        self.latest: T | None = None
        self._subscribers: set[asyncio.Queue[T]] = set()

    def publish(self, item: T) -> None:
        self.latest = item
        for queue in self._subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(item)

    def subscribe(self) -> asyncio.Queue[T]:
        queue: asyncio.Queue[T] = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[T]) -> None:
        self._subscribers.discard(queue)


class PublishStats:
    def __init__(self) -> None:
        self.published = 0
        self.skipped_ticks = 0
        self.last_compute_seconds = 0.0


class Publishes[T](Protocol):
    def publish(self, item: T) -> None: ...


async def publish_loop[T](
    compute: Callable[[], Awaitable[T | None]],
    hub: Publishes[T],
    interval_seconds: float = 1.0,
    stats: PublishStats | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_iterations: int | None = None,
) -> None:
    """Compute and publish every interval. Ticks missed by slow work are skipped, not queued."""
    stats = stats or PublishStats()
    due = clock()
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        started = clock()
        snapshot = await compute()
        stats.last_compute_seconds = clock() - started
        if snapshot is not None:
            hub.publish(snapshot)
            stats.published += 1
        due += interval_seconds
        now = clock()
        if now > due:
            missed = math.ceil((now - due) / interval_seconds)
            stats.skipped_ticks += missed
            due += missed * interval_seconds
        await sleep(max(due - now, 0))
