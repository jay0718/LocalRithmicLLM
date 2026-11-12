import asyncio
import collections
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from lrl_collector.replay import ALL_SYMBOLS, FaultConfig, ReplaySource, inject_faults
from lrl_collector.synthetic import MarketConfig, SyntheticMarket
from lrl_common.events import OpenInterest, Quote, Trade, idempotency_key

SMALL = MarketConfig(strikes_each_side=2, expiry_days=(30, 60))
BASE = {"source": "t", "exchange": "CME"}


def trade(ts_s: float, seq: int = 0, symbol: str = "ES") -> Trade:
    return Trade(**BASE, symbol=symbol, exchange_ts_ns=int(ts_s * 1e9), seq=seq, price=1, size=1)


def test_same_seed_gives_identical_output() -> None:
    assert list(SyntheticMarket(SMALL).events(200)) == list(SyntheticMarket(SMALL).events(200))


def test_different_seeds_differ() -> None:
    other = replace(SMALL, seed=8)
    assert list(SyntheticMarket(SMALL).events(50)) != list(SyntheticMarket(other).events(50))


def test_chain_covers_expiries_rights_and_strikes() -> None:
    contracts = SyntheticMarket(SMALL).contracts
    assert len(contracts) == 2 * 5 * 2
    assert len({c.symbol for c in contracts}) == len(contracts)
    assert {c.is_call for c in contracts} == {True, False}
    assert len({c.expiry for c in contracts}) == 2


def test_every_contract_opens_with_quote_and_open_interest() -> None:
    market = SyntheticMarket(SMALL)
    opening = list(market.events(0))
    symbols = {c.symbol for c in market.contracts}
    assert {e.symbol for e in opening if isinstance(e, OpenInterest)} == symbols
    assert {e.symbol for e in opening if isinstance(e, Quote)} == symbols | {SMALL.underlying}


def test_open_interest_peaks_near_the_money() -> None:
    wide = SyntheticMarket(replace(SMALL, strikes_each_side=40))
    values = {e.symbol: e.open_interest for e in wide.events(0) if isinstance(e, OpenInterest)}
    near = [values[c.symbol] for c in wide.contracts if c.strike == 6000]
    far = [values[c.symbol] for c in wide.contracts if c.strike == 7000]
    assert min(near) > max(far)


def test_quotes_are_valid_and_time_never_goes_backward() -> None:
    events = list(SyntheticMarket(SMALL).events(300))
    times = [e.exchange_ts_ns for e in events]
    assert times == sorted(times)
    for event in events:
        if isinstance(event, Quote):
            assert 0 <= event.bid_price < event.ask_price


def test_event_keys_are_unique() -> None:
    events = list(SyntheticMarket(SMALL).events(300))
    assert len({idempotency_key(e) for e in events}) == len(events)


async def collect(source: ReplaySource) -> list:
    await source.connect()
    return [event async for event in source.stream()]


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.mark.parametrize(("speed", "expected"), [(1, [1.0, 2.0]), (2, [0.5, 1.0]), (100, [0.01, 0.02])])
async def test_speed_scales_recorded_gaps(speed: float, expected: list[float]) -> None:
    fake = FakeTime()
    source = ReplaySource([trade(0), trade(1, 1), trade(3, 2)], speed=speed, clock=fake.clock, sleep=fake.sleep)
    await source.subscribe([ALL_SYMBOLS])
    assert len(await collect(source)) == 3
    assert fake.sleeps == pytest.approx(expected)


async def test_late_events_do_not_accumulate_delay() -> None:
    fake = FakeTime()

    async def slow_sleep(seconds: float) -> None:
        fake.sleeps.append(seconds)
        fake.now += seconds + 0.1

    source = ReplaySource([trade(0), trade(1, 1), trade(2, 2)], speed=1, clock=fake.clock, sleep=slow_sleep)
    await source.subscribe([ALL_SYMBOLS])
    await collect(source)
    assert fake.sleeps == pytest.approx([1.0, 0.9])


async def test_max_speed_never_sleeps() -> None:
    fake = FakeTime()
    source = ReplaySource([trade(0), trade(100, 1)], clock=fake.clock, sleep=fake.sleep)
    await source.subscribe([ALL_SYMBOLS])
    assert len(await collect(source)) == 2
    assert fake.sleeps == []


async def test_lagging_replay_does_not_starve_the_event_loop() -> None:
    source = ReplaySource([trade(0, i) for i in range(5000)], speed=1)
    await source.subscribe([ALL_SYMBOLS])
    ran_during_replay = asyncio.Event()

    async def other_work() -> None:
        ran_during_replay.set()

    task = asyncio.create_task(other_work())
    seen_before_end = False
    async for event in source.stream():
        if event.seq == 4999:
            seen_before_end = ran_during_replay.is_set()
    await task
    assert seen_before_end


def test_rejects_invalid_speed() -> None:
    with pytest.raises(ValueError):
        ReplaySource([], speed=0)


async def test_only_subscribed_symbols_are_delivered() -> None:
    source = ReplaySource([trade(0, 0, "A"), trade(0, 0, "B")])
    await source.subscribe(["B"])
    assert [e.symbol for e in await collect(source)] == ["B"]


async def test_nothing_is_delivered_without_a_subscription() -> None:
    assert await collect(ReplaySource([trade(0)])) == []


async def test_close_stops_the_stream() -> None:
    source = ReplaySource([trade(i, i) for i in range(10)])
    await source.subscribe([ALL_SYMBOLS])
    received = []
    async for event in source.stream():
        received.append(event)
        await source.close()
    assert len(received) == 1


EVENTS = [trade(i, i) for i in range(2000)]


def test_no_faults_changes_nothing() -> None:
    assert list(inject_faults(EVENTS, FaultConfig())) == EVENTS


def test_faults_are_deterministic() -> None:
    faults = FaultConfig(drop=0.1, duplicate=0.1, reorder=0.1, seed=3)
    assert list(inject_faults(EVENTS, faults)) == list(inject_faults(EVENTS, faults))


def test_drop_removes_events() -> None:
    result = list(inject_faults(EVENTS, FaultConfig(drop=0.1, seed=1)))
    assert 1700 < len(result) < 1900
    assert set(result) <= set(EVENTS)


def test_duplicate_repeats_events() -> None:
    result = list(inject_faults(EVENTS, FaultConfig(duplicate=0.1, seed=1)))
    counts = collections.Counter(e.seq for e in result)
    assert 100 < sum(1 for n in counts.values() if n == 2) < 300
    assert set(counts) == set(range(2000))


def test_reorder_keeps_every_event_but_changes_order() -> None:
    result = list(inject_faults(EVENTS, FaultConfig(reorder=0.1, seed=1)))
    assert sorted(e.seq for e in result) == list(range(2000))
    assert [e.seq for e in result] != list(range(2000))


def test_reorder_flushes_a_held_final_event() -> None:
    assert list(inject_faults([trade(0)], FaultConfig(reorder=1.0))) == [trade(0)]


async def test_replay_source_applies_faults() -> None:
    source = ReplaySource(EVENTS, faults=FaultConfig(drop=0.5, seed=2))
    await source.subscribe([ALL_SYMBOLS])
    assert len(await collect(source)) < 1500


@pytest.mark.parametrize("code", ["ES", "NQ", "RTY", "YM"])
def test_products_have_consistent_chains(code: str) -> None:
    from lrl_collector.synthetic import PRODUCTS

    config = PRODUCTS[code]
    market = SyntheticMarket(replace(config, strikes_each_side=2, expiry_days=(30,)))
    strikes = sorted({c.strike for c in market.contracts})
    assert all(abs(b - a - config.strike_step) < 1e-9 for a, b in zip(strikes, strikes[1:], strict=False))
    events = list(market.events(200))
    assert events == list(SyntheticMarket(replace(config, strikes_each_side=2, expiry_days=(30,))).events(200))
    prices = [e.bid_price for e in events if isinstance(e, Quote) and e.symbol == config.underlying]
    assert all(abs(p / config.tick - round(p / config.tick)) < 1e-6 for p in prices)
    assert all(abs(p - config.start_price) / config.start_price < 0.05 for p in prices)


def test_history_is_continuous_deterministic_and_in_session() -> None:
    from lrl_collector.synthetic import PRODUCTS, generate_history
    from lrl_common.bars import aggregate, is_session_minute, trading_date

    config = PRODUCTS["ES"]
    history = generate_history(config, sessions=3)
    assert history == generate_history(config, sessions=3)
    assert history[-1].close == config.start_price
    assert history[-1].start_ns < config.start.timestamp() * 1e9
    starts = [bar.start_ns for bar in history]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    assert all(is_session_minute(datetime.fromtimestamp(s / 1e9, UTC)) for s in starts)
    assert all(bar.low <= min(bar.open, bar.close) and bar.high >= max(bar.open, bar.close) for bar in history)
    assert all(b.open == a.close for a, b in zip(history, history[1:], strict=False))
    # Three complete prior sessions plus the overnight part of the replay day.
    assert len({trading_date(s) for s in starts}) == 4
    assert len(aggregate(history, "1d")) == 4


def test_session_hours() -> None:
    from lrl_common.bars import NEW_YORK, is_session_minute

    def at(day: int, hour: int) -> datetime:
        return datetime(2026, 11, day, hour, 0, tzinfo=NEW_YORK)

    assert is_session_minute(at(9, 10))  # Monday morning
    assert not is_session_minute(at(9, 17))  # daily halt
    assert not is_session_minute(at(6, 18))  # Friday evening
    assert not is_session_minute(at(7, 12))  # Saturday
    assert not is_session_minute(at(8, 12))  # Sunday before the open
    assert is_session_minute(at(8, 18))  # Sunday open
