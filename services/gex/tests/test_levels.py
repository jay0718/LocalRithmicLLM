from datetime import date

import pytest
from lrl_common.bars import NEW_YORK, Bar
from lrl_gex.levels import central_pivot_range, prior_session_cpr


def test_cpr_matches_hand_calculation() -> None:
    # H=110, L=90, C=105: P=101.667, BC=100, TC=103.333, R1=113.333, S1=93.333, R2=121.667, S2=81.667
    cpr = central_pivot_range(110, 90, 105, date(2026, 11, 6))
    assert cpr.pivot == pytest.approx(101.6667, abs=1e-3)
    assert (cpr.bc, cpr.tc) == pytest.approx((100, 103.3333), abs=1e-3)
    assert (cpr.r1, cpr.s1) == pytest.approx((113.3333, 93.3333), abs=1e-3)
    assert (cpr.r2, cpr.s2) == pytest.approx((121.6667, 81.6667), abs=1e-3)
    assert cpr.width_pct == pytest.approx(3.3333 / 101.6667 * 100, abs=1e-3)


def test_tc_is_always_the_upper_bound() -> None:
    cpr = central_pivot_range(110, 90, 92, date(2026, 11, 6))
    assert cpr.tc > cpr.bc
    assert cpr.tc == pytest.approx(100)


def ns(day: int, hour: int) -> int:
    from datetime import datetime

    return int(datetime(2026, 11, day, hour, tzinfo=NEW_YORK).timestamp() * 1e9)


def bar(start_ns: int, high: float, low: float, close: float) -> Bar:
    return Bar(start_ns=start_ns, open=close, high=high, low=low, close=close, volume=1, trades=1)


def test_uses_the_last_complete_session() -> None:
    bars = [
        bar(ns(5, 10), 100, 95, 98),  # Thursday
        bar(ns(6, 10), 120, 101, 110),  # Friday: the prior session for Monday
        bar(ns(6, 15), 125, 105, 115),
        bar(ns(8, 19), 130, 129, 129),  # Sunday evening belongs to Monday
    ]
    cpr = prior_session_cpr(bars)
    assert cpr.session_date == date(2026, 11, 6)
    assert (cpr.high, cpr.low, cpr.close) == (125, 101, 115)


def test_no_prior_session() -> None:
    assert prior_session_cpr([]) is None
    assert prior_session_cpr([bar(ns(9, 10), 1, 1, 1)]) is None
