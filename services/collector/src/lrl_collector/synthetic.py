"""Deterministic synthetic ES futures and option data for tests, load runs and demos."""

import math
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from lrl_common.bars import NEW_YORK, Bar, is_session_minute
from lrl_common.black76 import price
from lrl_common.contracts import OptionContract
from lrl_common.events import OpenInterest, Quote, SequenceCounter, Trade

_NS_PER_YEAR = 365 * 86_400 * 1_000_000_000
_RATE = 0.04

MarketEvent = Trade | Quote | OpenInterest


@dataclass(frozen=True)
class MarketConfig:
    seed: int = 7
    underlying: str = "ESZ6"
    exchange: str = "CME"
    start_price: float = 6000.0
    start: datetime = datetime(2026, 11, 9, 14, 30, tzinfo=UTC)
    expiry_days: tuple[int, ...] = (39, 130, 221)
    strike_step: float = 25.0
    tick: float = 0.25
    strikes_each_side: int = 40
    base_vol: float = 0.18
    mean_gap_ms: float = 20.0
    option_updates_per_tick: int = 5


def product_config(underlying: str, exchange: str, price: float, step: float, tick: float, vol: float) -> MarketConfig:
    """A chain covering about 8% either side of price, at the product's strike spacing."""
    return MarketConfig(
        underlying=underlying,
        exchange=exchange,
        start_price=price,
        strike_step=step,
        strikes_each_side=round(price * 0.08 / step),
        tick=tick,
        base_vol=vol,
    )


# Starting levels are the Rithmic Test settles for 2026-11-11 (5pm ET). They anchor the
# synthetic data near real prices; they are not live data.
PRODUCTS: dict[str, MarketConfig] = {
    "ES": product_config("ESZ6", "CME", 7646.0, 5.0, 0.25, 0.18),
    "NQ": product_config("NQZ6", "CME", 27341.0, 25.0, 0.25, 0.22),
    "RTY": product_config("RTYZ6", "CME", 2770.6, 5.0, 0.1, 0.24),
    "YM": product_config("YMZ6", "CBOT", 52390.0, 50.0, 1.0, 0.16),
}


def session_start(day: datetime) -> datetime:
    """9:30 New York time on the given day, or on the previous weekday for a weekend."""
    local = day.astimezone(NEW_YORK)
    while local.weekday() >= 5:
        local -= timedelta(days=1)
    return local.replace(hour=9, minute=30, second=0, microsecond=0).astimezone(UTC)


class SyntheticMarket:
    """A seeded futures random walk with a full option chain priced off it."""

    def __init__(self, config: MarketConfig | None = None) -> None:
        self.config = config or MarketConfig()
        self.contracts = self._build_contracts()
        self._rng = random.Random(self.config.seed)
        self._sequence = SequenceCounter()
        self._now_ns = int(self.config.start.timestamp() * 1e9)
        self._price = self.config.start_price

    def _build_contracts(self) -> list[OptionContract]:
        config = self.config
        center = round(config.start_price / config.strike_step) * config.strike_step
        strikes = [
            center + i * config.strike_step for i in range(-config.strikes_each_side, config.strikes_each_side + 1)
        ]
        contracts = []
        for days in config.expiry_days:
            expiry = config.start + timedelta(days=days)
            for strike in strikes:
                for right, is_call in (("C", True), ("P", False)):
                    contracts.append(
                        OptionContract(
                            symbol=f"{config.underlying} {expiry:%y%m%d} {right}{strike:g}",
                            underlying=config.underlying,
                            expiry=f"{expiry:%Y%m%d}",
                            expiry_ts_ns=int(expiry.timestamp() * 1e9),
                            strike=strike,
                            is_call=is_call,
                        )
                    )
        return contracts

    def _common(self, symbol: str) -> dict:
        return {
            "source": "replay",
            "symbol": symbol,
            "exchange": self.config.exchange,
            "exchange_ts_ns": self._now_ns,
            "seq": self._sequence.next(symbol),
        }

    def _vol(self, contract: OptionContract) -> float:
        moneyness = math.log(contract.strike / self._price)
        return max(0.05, self.config.base_vol * (1 - 1.2 * moneyness + 5 * moneyness * moneyness))

    def _option_quote(self, contract: OptionContract) -> Quote:
        expiry_years = (contract.expiry_ts_ns - self._now_ns) / _NS_PER_YEAR
        mid = float(price(self._price, contract.strike, expiry_years, _RATE, self._vol(contract), contract.is_call))
        return Quote(
            **self._common(contract.symbol),
            bid_price=max(mid - self.config.tick, 0.0),
            bid_size=self._rng.randint(1, 50),
            ask_price=mid + self.config.tick,
            ask_size=self._rng.randint(1, 50),
        )

    def _open_interest(self, contract: OptionContract) -> OpenInterest:
        distance = (contract.strike - self.config.start_price) / self.config.start_price
        favored = (distance > 0) == contract.is_call
        hump = math.exp(-((distance / 0.05) ** 2)) * (1.6 if favored else 1.0)
        return OpenInterest(
            **self._common(contract.symbol), open_interest=int(20_000 * hump * self._rng.uniform(0.6, 1.4))
        )

    def _futures_quote(self) -> Quote:
        return Quote(
            **self._common(self.config.underlying),
            bid_price=self._price - self.config.tick,
            bid_size=self._rng.randint(1, 200),
            ask_price=self._price + self.config.tick,
            ask_size=self._rng.randint(1, 200),
        )

    def events(self, ticks: int) -> Iterator[MarketEvent]:
        """Yield the opening chain, then the given number of market ticks."""
        yield self._futures_quote()
        for contract in self.contracts:
            yield self._open_interest(contract)
            yield self._option_quote(contract)

        for _ in range(ticks):
            self._now_ns += int(self._rng.expovariate(1 / self.config.mean_gap_ms) * 1e6)
            self._price += self._rng.choice((-self.config.tick, 0.0, self.config.tick))
            yield self._futures_quote()
            if self._rng.random() < 0.3:
                yield Trade(**self._common(self.config.underlying), price=self._price, size=self._rng.randint(1, 20))
            for contract in self._rng.sample(self.contracts, self.config.option_updates_per_tick):
                yield self._option_quote(contract)


_MINUTES_PER_YEAR = 252 * 23 * 60


def generate_history(config: MarketConfig, sessions: int = 10, seed: int | None = None) -> list[Bar]:
    """One-minute bars for the trading sessions before the replay starts, ending at its start price.

    The walk is generated forward, then shifted so the last close meets the
    replay's opening price, which keeps history and live data continuous.
    """
    rng = random.Random(config.seed if seed is None else seed)
    end = config.start.astimezone(UTC).replace(second=0, microsecond=0)
    minutes: list[datetime] = []
    cursor = end - timedelta(minutes=1)
    trading_days: set[object] = set()
    while True:
        if is_session_minute(cursor):
            day = (cursor.astimezone(NEW_YORK) + timedelta(hours=6)).date()
            trading_days.add(day)
            if len(trading_days) > sessions + 1:
                break
            minutes.append(cursor)
        cursor -= timedelta(minutes=1)
    minutes.reverse()

    sigma = config.base_vol / math.sqrt(_MINUTES_PER_YEAR)
    moves = [rng.gauss(0, sigma) for _ in minutes]
    log_level = 0.0
    closes = []
    for move in moves:
        log_level += move
        closes.append(log_level)
    shift = -closes[-1] if closes else 0.0

    def snap(value: float) -> float:
        return round(value / config.tick) * config.tick

    bars: list[Bar] = []
    previous = snap(config.start_price * math.exp(closes[0] - moves[0] + shift)) if closes else config.start_price
    for minute, level in zip(minutes, closes, strict=True):
        close = snap(config.start_price * math.exp(level + shift))
        wiggle = abs(rng.gauss(0, sigma)) * config.start_price
        high = snap(max(previous, close) + wiggle)
        low = snap(min(previous, close) - abs(rng.gauss(0, sigma)) * config.start_price)
        local = minute.astimezone(NEW_YORK)
        regular_hours = (local.hour, local.minute) >= (9, 30) and local.hour < 16
        volume = rng.randint(400, 3000) if regular_hours else rng.randint(20, 400)
        bars.append(
            Bar(
                start_ns=int(minute.timestamp() * 1e9),
                open=previous,
                high=high,
                low=low,
                close=close,
                volume=volume,
                trades=max(volume // 3, 1),
            )
        )
        previous = close
    if bars:
        last = bars[-1]
        bars[-1] = last.model_copy(
            update={
                "close": snap(config.start_price),
                "high": max(last.high, snap(config.start_price)),
                "low": min(last.low, snap(config.start_price)),
            }
        )
    return bars
