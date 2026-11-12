"""The interface every model backend implements."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from ..models import ChatCompletionRequest


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Finished:
    reason: str
    prompt_tokens: int
    completion_tokens: int


ProviderEvent = TextDelta | Finished


class ProviderError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after


class Provider(Protocol):
    def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ProviderEvent]:
        """Yield text deltas followed by exactly one Finished event."""
        ...
