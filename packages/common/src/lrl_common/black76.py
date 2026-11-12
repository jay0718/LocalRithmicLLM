"""Vectorized Black-76 pricing for options on futures.

Inputs may be scalars or arrays. Outputs never contain NaN: contracts that cannot
be valued get intrinsic value and zero gamma, and failed implied volatility
solves are flagged instead.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.special import ndtr

Float = NDArray[np.float64]

MIN_VOL = 1e-4
MAX_VOL = 5.0
_SOLVER_ITERATIONS = 100


def _arrays(*values: ArrayLike) -> list[Float]:
    return [np.asarray(value, dtype=float) for value in values]


def _d1(forward: Float, strike: Float, expiry: Float, vol: Float) -> Float:
    return (np.log(forward / strike) + 0.5 * vol * vol * expiry) / (vol * np.sqrt(expiry))


def _is_valid(forward: Float, strike: Float, expiry: Float, vol: Float) -> NDArray[np.bool_]:
    finite = np.isfinite(forward) & np.isfinite(strike) & np.isfinite(expiry) & np.isfinite(vol)
    with np.errstate(invalid="ignore"):
        return finite & (forward > 0) & (strike > 0) & (expiry > 0) & (vol > 0)


def intrinsic(forward: ArrayLike, strike: ArrayLike, rate: ArrayLike, expiry: ArrayLike, is_call: ArrayLike) -> Float:
    """Discounted intrinsic value. Non-finite inputs and past expiries are treated as undiscounted."""
    f, k, r, t = _arrays(forward, strike, rate, expiry)
    payoff = np.where(np.asarray(is_call, dtype=bool), f - k, k - f)
    discount = np.exp(-r * np.maximum(np.nan_to_num(t), 0))
    return np.nan_to_num(discount * np.maximum(payoff, 0))


def price(
    forward: ArrayLike, strike: ArrayLike, expiry: ArrayLike, rate: ArrayLike, vol: ArrayLike, is_call: ArrayLike
) -> Float:
    f, k, t, r, s = _arrays(forward, strike, expiry, rate, vol)
    call = np.asarray(is_call, dtype=bool)
    f, k, t, r, s, call = np.broadcast_arrays(f, k, t, r, s, call)
    result = intrinsic(f, k, r, t, call)
    ok = _is_valid(f, k, t, s)
    if np.any(ok):
        d1 = _d1(f[ok], k[ok], t[ok], s[ok])
        d2 = d1 - s[ok] * np.sqrt(t[ok])
        discount = np.exp(-r[ok] * t[ok])
        calls = discount * (f[ok] * ndtr(d1) - k[ok] * ndtr(d2))
        puts = discount * (k[ok] * ndtr(-d2) - f[ok] * ndtr(-d1))
        result = np.array(result, dtype=float)
        result[ok] = np.where(call[ok], calls, puts)
    return result


def gamma(forward: ArrayLike, strike: ArrayLike, expiry: ArrayLike, rate: ArrayLike, vol: ArrayLike) -> Float:
    """Second derivative of price with respect to the futures price, the same for calls and puts."""
    f, k, t, r, s = np.broadcast_arrays(*_arrays(forward, strike, expiry, rate, vol))
    result = np.zeros_like(f, dtype=float)
    ok = _is_valid(f, k, t, s)
    if np.any(ok):
        d1 = _d1(f[ok], k[ok], t[ok], s[ok])
        density = np.exp(-0.5 * d1 * d1) / np.sqrt(2 * np.pi)
        result[ok] = np.exp(-r[ok] * t[ok]) * density / (f[ok] * s[ok] * np.sqrt(t[ok]))
    return result


@dataclass(frozen=True)
class ImpliedVol:
    """vol is 0 wherever converged is False."""

    vol: Float
    converged: NDArray[np.bool_]


def implied_vol(
    target: ArrayLike,
    forward: ArrayLike,
    strike: ArrayLike,
    expiry: ArrayLike,
    rate: ArrayLike,
    is_call: ArrayLike,
    tolerance: float = 1e-7,
) -> ImpliedVol:
    """Solve for volatility by bisection, which is safe for any quote within no-arbitrage bounds."""
    p, f, k, t, r = np.broadcast_arrays(*_arrays(target, forward, strike, expiry, rate))
    call = np.broadcast_to(np.asarray(is_call, dtype=bool), p.shape)

    low_price = price(f, k, t, r, np.full_like(p, MIN_VOL), call)
    high_price = price(f, k, t, r, np.full_like(p, MAX_VOL), call)
    with np.errstate(invalid="ignore"):
        solvable = _is_valid(f, k, t, np.ones_like(p)) & np.isfinite(p) & (p > low_price) & (p < high_price)

    low = np.full_like(p, MIN_VOL, dtype=float)
    high = np.full_like(p, MAX_VOL, dtype=float)
    for _ in range(_SOLVER_ITERATIONS):
        middle = 0.5 * (low + high)
        below = price(f, k, t, r, middle, call) < p
        low = np.where(below, middle, low)
        high = np.where(below, high, middle)
        if np.all(high[solvable] - low[solvable] < tolerance):
            break

    vol = np.where(solvable, 0.5 * (low + high), 0.0)
    return ImpliedVol(vol=vol, converged=np.asarray(solvable))
