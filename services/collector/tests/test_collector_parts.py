"""Collector logic that needs no Rithmic kit."""

import asyncio

import pytest
from lrl_collector.backoff import Backoff
from lrl_collector.buffer import BoundedBuffer
from lrl_collector.quotes import ASK, BID, QuoteBook


def test_backoff_grows_to_cap_with_full_jitter() -> None:
    backoff = Backoff(base_seconds=1, cap_seconds=8, rng=lambda: 1.0)
    assert [backoff.next_delay() for _ in range(6)] == [1, 2, 4, 8, 8, 8]
    backoff.reset()
    assert backoff.next_delay() == 1
    assert Backoff(rng=lambda: 0.0).next_delay() == 0


def test_backoff_jitter_stays_within_ceiling() -> None:
    backoff = Backoff(base_seconds=1, cap_seconds=60)
    for attempt in range(10):
        assert 0 <= backoff.next_delay() <= min(60, 2**attempt)


async def test_buffer_drops_and_counts_when_full() -> None:
    buffer: BoundedBuffer[int] = BoundedBuffer(maxsize=2, put_timeout_seconds=0.01)
    assert [await buffer.put(i) for i in range(4)] == [True, True, False, False]
    assert buffer.dropped == 2
    assert [await buffer.get(), await buffer.get()] == [0, 1]


async def test_buffer_waits_for_space_before_dropping() -> None:
    buffer: BoundedBuffer[int] = BoundedBuffer(maxsize=1, put_timeout_seconds=1)
    await buffer.put(1)
    pending = asyncio.create_task(buffer.put(2))
    await asyncio.sleep(0.01)
    assert await buffer.get() == 1
    assert await pending
    assert buffer.dropped == 0


def test_quote_book_merges_partial_updates() -> None:
    book = QuoteBook()
    assert book.apply("ES", BID | ASK, 0, 100, 5, 100.25, 7) == (100, 5, 100.25, 7)
    assert book.apply("ES", BID, 0, 99.75, 3, 0, 0) == (99.75, 3, 100.25, 7)
    assert book.apply("ES", 0, ASK, 0, 0, 0, 0) == (99.75, 3, None, None)


def test_quote_book_is_per_symbol_and_resets() -> None:
    book = QuoteBook()
    book.apply("A", BID, 0, 1, 1, 0, 0)
    assert book.apply("B", ASK, 0, 0, 0, 2, 2) == (None, None, 2, 2)
    book.reset()
    assert book.apply("A", ASK, 0, 0, 0, 3, 3) == (None, None, 3, 3)


@pytest.mark.parametrize("present", [0, BID])
def test_clear_wins_over_presence(present: int) -> None:
    book = QuoteBook()
    book.apply("ES", BID, 0, 1, 1, 0, 0)
    assert book.apply("ES", present, BID, 9, 9, 0, 0)[:2] == (None, None)
