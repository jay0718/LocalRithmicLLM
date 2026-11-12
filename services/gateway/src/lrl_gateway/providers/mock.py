"""A controllable backend for tests and load runs, with no model or API costs.

Failures are chosen by model name so they work through any OpenAI client:
mock:429, mock:500, mock:timeout and mock:disconnect.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from ..models import ChatCompletionRequest
from .base import Finished, ProviderError, ProviderEvent, TextDelta


@dataclass(frozen=True)
class MockConfig:
    time_to_first_token_seconds: float = 0
    tokens_per_second: float | None = None
    reply: str = "This is a response from the mock provider."
    disconnect_after_tokens: int = 2


class MockProvider:
    def __init__(self, config: MockConfig | None = None) -> None:
        self.config = config or MockConfig()

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ProviderEvent]:
        failure = request.model.partition(":")[2]
        if self.config.time_to_first_token_seconds:
            await asyncio.sleep(self.config.time_to_first_token_seconds)
        if failure == "429":
            raise ProviderError(429, "rate_limited", "Mock rate limit", retry_after=1)
        if failure == "500":
            raise ProviderError(500, "upstream_error", "Mock server error")
        if failure == "timeout":
            await asyncio.Event().wait()
        if failure not in ("", "disconnect"):
            raise ProviderError(404, "model_not_found", f"Unknown mock failure mode: {failure}")

        words = self.config.reply.split(" ")
        for index, word in enumerate(words):
            if failure == "disconnect" and index == self.config.disconnect_after_tokens:
                raise ProviderError(502, "upstream_disconnected", "Mock upstream disconnected")
            if index and self.config.tokens_per_second:
                await asyncio.sleep(1 / self.config.tokens_per_second)
            yield TextDelta(word if index == 0 else f" {word}")
        prompt_tokens = sum(len(message.content.split()) for message in request.messages)
        yield Finished("stop", prompt_tokens, len(words))
