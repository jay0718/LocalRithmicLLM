"""A bounded buffer between the feed reader and the publisher."""

import asyncio
from typing import TypeVar

T = TypeVar("T")


class BoundedBuffer[T]:
    """Waits up to put_timeout for space, then drops the item and counts it.

    The server cannot be slowed down, so an unbounded wait would only move the
    backlog into the socket until Rithmic disconnects a slow consumer. Dropped
    events surface downstream as gaps and in the dropped counter.
    """

    def __init__(self, maxsize: int, put_timeout_seconds: float) -> None:
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=maxsize)
        self._put_timeout = put_timeout_seconds
        self.dropped = 0

    async def put(self, item: T) -> bool:
        try:
            await asyncio.wait_for(self._queue.put(item), self._put_timeout)
            return True
        except TimeoutError:
            self.dropped += 1
            return False

    async def get(self) -> T:
        return await self._queue.get()

    def qsize(self) -> int:
        return self._queue.qsize()
