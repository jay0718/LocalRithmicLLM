import numpy as np
import pytest
from lrl_common.black76 import gamma, implied_vol, price


def test_hull_textbook_example() -> None:
    # Hull, Options, Futures, and Other Derivatives: F=K=20, r=9%, T=4 months, vol=25% gives 1.12.
    assert price(20, 20, 4 / 12, 0.09, 0.25, True) == pytest.approx(1.12, abs=0.005)
    assert price(20, 20, 4 / 12, 0.09, 0.25, False) == pytest.approx(1.12, abs=0.005)


def test_reference_values() -> None:
    # F=K=100, T=1, r=0, vol=20%: d1=0.1, N(0.1)=0.5398278.
    assert price(100, 100, 1, 0, 0.2, True) == pytest.approx(100 * (2 * 0.5398278 - 1), abs=1e-4)
    # gamma = pdf(0.1) / (F * vol * sqrt(T)) = 0.3969525 / 20.
    assert gamma(100, 100, 1, 0, 0.2) == pytest.approx(0.01984763, abs=1e-7)


def test_put_call_parity() -> None:
    strikes = np.linspace(50, 150, 21)
    difference = price(100, strikes, 0.5, 0.04, 0.3, True) - price(100, strikes, 0.5, 0.04, 0.3, False)
    assert difference == pytest.approx(np.exp(-0.04 * 0.5) * (100 - strikes))


def test_gamma_matches_finite_difference() -> None:
    bump = 0.01
    strikes = np.array([80.0, 100.0, 120.0])
    up, mid, down = (price(100 + b, strikes, 0.5, 0.03, 0.25, True) for b in (bump, 0, -bump))
    assert gamma(100, strikes, 0.5, 0.03, 0.25) == pytest.approx((up - 2 * mid + down) / bump**2, rel=1e-4)


def test_vectorized_results_match_scalars() -> None:
    strikes = np.array([90.0, 100.0, 110.0])
    calls = np.array([True, False, True])
    expected = [price(100, k, 1, 0.01, 0.2, c) for k, c in zip(strikes, calls, strict=True)]
    assert price(100, strikes, 1, 0.01, 0.2, calls) == pytest.approx(np.array(expected))


@pytest.mark.parametrize("is_call", [True, False])
def test_implied_vol_round_trip(is_call: bool) -> None:
    strikes = np.linspace(80, 120, 41)
    vols = np.linspace(0.1, 0.8, 41)
    result = implied_vol(price(100, strikes, 0.25, 0.02, vols, is_call), 100, strikes, 0.25, 0.02, is_call)
    assert result.converged.all()
    assert result.vol == pytest.approx(vols, abs=1e-5)


def test_expired_option_is_intrinsic_with_zero_gamma() -> None:
    assert price(110, 100, 0, 0.05, 0.2, True) == pytest.approx(10)
    assert price(110, 100, -1, 0.05, 0.2, False) == pytest.approx(0)
    assert gamma(110, 100, 0, 0.05, 0.2) == 0


@pytest.mark.parametrize(
    ("forward", "strike", "expiry", "vol"),
    [(np.nan, 100, 1, 0.2), (100, np.nan, 1, 0.2), (100, 100, np.nan, 0.2), (100, 100, 1, np.nan), (0, 100, 1, 0.2)],
)
def test_bad_inputs_never_produce_nan(forward: float, strike: float, expiry: float, vol: float) -> None:
    assert np.isfinite(price(forward, strike, expiry, 0.01, vol, True))
    assert gamma(forward, strike, expiry, 0.01, vol) == 0


def test_extreme_strikes_stay_finite() -> None:
    strikes = np.array([1e-3, 1.0, 1e6])
    assert np.isfinite(price(100, strikes, 1, 0.01, 0.2, True)).all()
    assert np.isfinite(gamma(100, strikes, 1, 0.01, 0.2)).all()


@pytest.mark.parametrize(
    ("target", "strike", "expiry", "is_call"),
    [
        (np.nan, 100, 1, True),  # no bid or ask
        (0.0, 150, 0.1, True),  # worthless quote
        (5.0, 80, 1, True),  # below intrinsic
        (500.0, 100, 1, True),  # above the maximum value
        (5.0, 100, 0, True),  # expired
    ],
)
def test_unsolvable_quotes_are_flagged(target: float, strike: float, expiry: float, is_call: bool) -> None:
    result = implied_vol(target, 100, strike, expiry, 0.01, is_call)
    assert not result.converged
    assert result.vol == 0


def test_one_bad_quote_does_not_affect_others() -> None:
    good = float(price(100, 100, 1, 0, 0.2, True))
    result = implied_vol(np.array([good, np.nan]), 100, 100, 1, 0, True)
    assert result.converged.tolist() == [True, False]
    assert result.vol[0] == pytest.approx(0.2, abs=1e-5)
