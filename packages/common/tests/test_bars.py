from lrl_common.bars import MINUTE_NS, BarBuilder
from lrl_common.events import OpenInterest, Quote, Trade

BASE = {"source": "t", "symbol": "ES", "exchange": "CME", "seq": 0}
T0 = 1000 * MINUTE_NS


def trade(ts: int, price: float, size: int = 1) -> Trade:
    return Trade(**BASE, exchange_ts_ns=ts, price=price, size=size)


def quote(ts: int, bid: float, ask: float) -> Quote:
    return Quote(**BASE, exchange_ts_ns=ts, bid_price=bid, ask_price=ask)


def test_trades_build_ohlc_and_volume() -> None:
    bars = BarBuilder("ES")
    for offset, price, size in ((1, 100, 2), (2, 103, 1), (3, 99, 4), (4, 101, 1)):
        bars.apply(trade(T0 + offset, price, size))
    (bar,) = bars.bars(10)
    assert (bar.start_ns, bar.open, bar.high, bar.low, bar.close, bar.volume, bar.trades) == (
        T0,
        100,
        103,
        99,
        101,
        8,
        4,
    )


def test_bars_close_on_minute_boundaries() -> None:
    bars = BarBuilder("ES")
    bars.apply(trade(T0 + 5, 100))
    bars.apply(trade(T0 + MINUTE_NS - 1, 101))
    bars.apply(trade(T0 + MINUTE_NS, 102))
    first, second = bars.bars(10)
    assert (first.start_ns, first.close) == (T0, 101)
    assert (second.start_ns, second.open) == (T0 + MINUTE_NS, 102)


def test_quiet_minutes_use_quote_mids_until_a_trade() -> None:
    bars = BarBuilder("ES")
    bars.apply(quote(T0 + 1, 99, 101))
    bars.apply(quote(T0 + 2, 103, 105))
    assert (bars.current.open, bars.current.high, bars.current.close, bars.current.trades) == (100, 104, 104, 0)
    bars.apply(trade(T0 + 3, 102))
    bars.apply(quote(T0 + 4, 120, 122))
    assert (bars.current.open, bars.current.high, bars.current.low, bars.current.close) == (102, 102, 102, 102)


def test_ignores_other_symbols_open_interest_and_one_sided_quotes() -> None:
    bars = BarBuilder("ES")
    bars.apply(Trade(**{**BASE, "symbol": "NQ"}, exchange_ts_ns=T0, price=1, size=1))
    bars.apply(OpenInterest(**BASE, exchange_ts_ns=T0, open_interest=5))
    bars.apply(Quote(**BASE, exchange_ts_ns=T0, bid_price=1, ask_price=None))
    assert bars.bars(10) == []


def test_older_minute_is_counted_not_applied() -> None:
    bars = BarBuilder("ES")
    bars.apply(trade(T0 + MINUTE_NS, 100))
    bars.apply(trade(T0, 50))
    assert bars.out_of_order == 1
    assert [bar.close for bar in bars.bars(10)] == [100]


def test_window_is_capped_and_limit_returns_latest() -> None:
    bars = BarBuilder("ES", max_bars=3)
    for minute in range(10):
        bars.apply(trade(T0 + minute * MINUTE_NS, minute))
    assert [bar.close for bar in bars.bars(100)] == [6, 7, 8, 9]
    assert [bar.close for bar in bars.bars(2)] == [8, 9]


def test_returned_bars_are_copies() -> None:
    bars = BarBuilder("ES")
    bars.apply(trade(T0, 100))
    bars.bars(1)[0].close = 0
    assert bars.current.close == 100


from datetime import UTC, date, datetime  # noqa: E402

from lrl_common.bars import Bar, aggregate, session_open_ns, trading_date  # noqa: E402


def ny_ns(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    from lrl_common.bars import NEW_YORK

    return int(datetime(year, month, day, hour, minute, tzinfo=NEW_YORK).timestamp() * 1e9)


def minute_bar(start_ns: int, open_: float, high: float, low: float, close: float, volume: int = 1) -> Bar:
    return Bar(start_ns=start_ns, open=open_, high=high, low=low, close=close, volume=volume, trades=1)


def test_trading_day_starts_at_6pm_new_york() -> None:
    assert trading_date(ny_ns(2026, 11, 5, 17, 59)) == date(2026, 11, 5)  # the 5pm halt closes the session
    assert trading_date(ny_ns(2026, 11, 5, 18, 0)) == date(2026, 11, 6)
    assert trading_date(ny_ns(2026, 11, 6, 16, 59)) == date(2026, 11, 6)
    assert trading_date(ny_ns(2026, 11, 8, 18, 0)) == date(2026, 11, 9)  # Sunday evening opens Monday
    assert session_open_ns(date(2026, 11, 9)) == ny_ns(2026, 11, 8, 18, 0)


def test_trading_day_handles_daylight_saving_change() -> None:
    # US clocks fell back on 2026-11-01; 6pm local is 23:00 UTC after and 22:00 UTC before.
    assert trading_date(int(datetime(2026, 11, 2, 23, 0, tzinfo=UTC).timestamp() * 1e9)) == date(2026, 11, 3)
    assert trading_date(int(datetime(2026, 10, 29, 22, 0, tzinfo=UTC).timestamp() * 1e9)) == date(2026, 10, 30)


def test_aggregate_five_minutes() -> None:
    start = ny_ns(2026, 11, 9, 9, 30)
    bars = [minute_bar(start + i * MINUTE_NS, 100 + i, 101 + i, 99 + i, 100.5 + i, volume=2) for i in range(7)]
    first, second = aggregate(bars, "5m")
    assert (first.start_ns, first.open, first.high, first.low, first.close, first.volume) == (
        start,
        100,
        105,
        99,
        104.5,
        10,
    )
    assert (second.start_ns, second.open, second.close, second.volume) == (start + 5 * MINUTE_NS, 105, 106.5, 4)


def test_aggregate_daily_follows_cme_sessions() -> None:
    bars = [
        minute_bar(ny_ns(2026, 11, 5, 18, 0), 10, 12, 9, 11),
        minute_bar(ny_ns(2026, 11, 6, 16, 59), 11, 15, 8, 14),
        minute_bar(ny_ns(2026, 11, 8, 18, 0), 14, 14, 13, 13),
    ]
    friday, monday = aggregate(bars, "1d")
    assert (friday.start_ns, friday.open, friday.high, friday.low, friday.close) == (
        ny_ns(2026, 11, 5, 18),
        10,
        15,
        8,
        14,
    )
    assert monday.start_ns == ny_ns(2026, 11, 8, 18)


def test_seed_then_live_events_continue_history() -> None:
    builder = BarBuilder("ES")
    builder.seed([minute_bar(T0 - MINUTE_NS, 1, 1, 1, 1)])
    builder.apply(trade(T0 + 1, 2))
    assert [bar.close for bar in builder.all_bars()] == [1, 2]


def test_events_already_in_seeded_history_are_ignored() -> None:
    builder = BarBuilder("ES")
    builder.seed([minute_bar(T0, 1, 2, 1, 2)])
    builder.apply(trade(T0 + MINUTE_NS, 2))  # the feed's snapshot of the last trade, stamped at the bar's end
    builder.apply(trade(T0 + 30, 9))
    assert [bar.close for bar in builder.all_bars()] == [2]
    builder.apply(trade(T0 + MINUTE_NS + 1, 3))
    assert [bar.close for bar in builder.all_bars()] == [2, 3]


def test_no_bars_form_during_the_halt() -> None:
    builder = BarBuilder("ES")
    builder.apply(quote(ny_ns(2026, 11, 11, 17, 35), 7645, 7647))
    builder.apply(trade(ny_ns(2026, 11, 14, 12, 0), 7646))  # Saturday
    assert builder.all_bars() == []
    builder.apply(trade(ny_ns(2026, 11, 11, 18, 1), 7646))
    assert len(builder.all_bars()) == 1


def test_backfill_fills_a_gap_and_leaves_the_forming_bar_alone() -> None:
    minute = 60_000_000_000
    builder = BarBuilder("ES")
    builder.session_hours_only = False

    def bar(m: int, close: float) -> Bar:
        return Bar(start_ns=m * minute, open=close, high=close, low=close, close=close, volume=1, trades=1)

    builder.seed([bar(100, 1.0), bar(101, 2.0)])
    # Live resumes at minute 105 after a dropped connection: 102 to 104 are missing.
    builder.apply(trade(105 * minute + 1, 9.0))
    assert [b.start_ns // minute for b in builder.all_bars()] == [100, 101, 105]
    added = builder.backfill([bar(101, 2.5), bar(102, 3.0), bar(103, 4.0), bar(104, 5.0), bar(105, 99.0)])
    assert added == 3
    assert [b.start_ns // minute for b in builder.all_bars()] == [100, 101, 102, 103, 104, 105]
    assert builder.all_bars()[1].close == 2.5  # the exchange's complete bar replaces the held one
    assert builder.current is not None and builder.current.close == 9.0  # forming bar untouched
