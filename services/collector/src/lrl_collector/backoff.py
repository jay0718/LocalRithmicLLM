"""Reconnect delays."""

import random
from collections.abc import Callable


class Backoff:
    """Exponential backoff with full jitter, so many clients don't reconnect in lockstep."""

    def __init__(
        self, base_seconds: float = 1.0, cap_seconds: float = 60.0, rng: Callable[[], float] = random.random
    ) -> None:
        self._base = base_seconds
        self._cap = cap_seconds
        self._rng = rng
        self.attempt = 0

    def next_delay(self) -> float:
        ceiling = min(self._cap, self._base * 2**self.attempt)
        self.attempt += 1
        return self._rng() * ceiling

    def reset(self) -> None:
        self.attempt = 0
