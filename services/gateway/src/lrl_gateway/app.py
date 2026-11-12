"""OpenAI-compatible chat completions API."""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from .models import ChatCompletionRequest, error_body
from .providers.base import Finished, Provider, ProviderError, ProviderEvent, TextDelta

_ERROR_TYPES = {400: "invalid_request_error", 404: "invalid_request_error", 429: "rate_limit_error"}


def _gateway_status(status: int) -> int:
    """Upstream 5xx responses are reported as a bad gateway, other codes pass through."""
    return 502 if status >= 500 and status != 504 else status


def _error_payload(error: ProviderError) -> dict:
    return error_body(error.message, _ERROR_TYPES.get(error.status, "api_error"), error.code)


def _sse(payload: dict | str) -> str:
    return f"data: {payload if isinstance(payload, str) else json.dumps(payload)}\n\n"


def create_app(providers: Mapping[str, Provider], first_token_timeout_seconds: float = 30) -> FastAPI:
    app = FastAPI(title="LocalRithmicLLM Gateway")

    def provider_for(model: str) -> Provider:
        provider = providers.get(model.partition(":")[0])
        if provider is None:
            raise ProviderError(404, "model_not_found", f"Unknown model: {model}")
        return provider

    async def first_event(events: AsyncIterator[ProviderEvent]) -> ProviderEvent:
        try:
            async with asyncio.timeout(first_token_timeout_seconds):
                return await anext(events)
        except TimeoutError:
            raise ProviderError(504, "first_token_timeout", "The model did not respond in time") from None
        except StopAsyncIteration:
            raise ProviderError(502, "empty_response", "The model returned no output") from None

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, error: RequestValidationError) -> JSONResponse:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in error.errors())
        return JSONResponse(status_code=400, content=error_body(problems, "invalid_request_error", "invalid_request"))

    @app.exception_handler(ProviderError)
    async def provider_error(_: Request, error: ProviderError) -> JSONResponse:
        headers = {"Retry-After": str(int(error.retry_after))} if error.retry_after else None
        return JSONResponse(status_code=_gateway_status(error.status), content=_error_payload(error), headers=headers)

    @app.post("/v1/chat/completions")
    async def chat_completions(body: ChatCompletionRequest):
        events = provider_for(body.model).stream(body)
        first = await first_event(events)
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        if body.stream:
            stream = _stream(body, completion_id, created, first, events)
            return StreamingResponse(stream, media_type="text/event-stream")
        return await _complete(body, completion_id, created, first, events)

    return app


async def _complete(
    body: ChatCompletionRequest,
    completion_id: str,
    created: int,
    first: ProviderEvent,
    events: AsyncIterator[ProviderEvent],
) -> dict:
    text: list[str] = []
    event = first
    while not isinstance(event, Finished):
        text.append(event.text)
        event = await anext(events)
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": body.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "".join(text)},
                "finish_reason": event.reason,
            }
        ],
        "usage": _usage(event),
    }


async def _stream(
    body: ChatCompletionRequest,
    completion_id: str,
    created: int,
    first: ProviderEvent,
    events: AsyncIterator[ProviderEvent],
) -> AsyncIterator[str]:
    def chunk(choices: list[dict], **extra: object) -> dict:
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": body.model,
            "choices": choices,
            **extra,
        }

    def delta(content: dict, finish_reason: str | None = None) -> dict:
        return chunk([{"index": 0, "delta": content, "finish_reason": finish_reason}])

    try:
        yield _sse(delta({"role": "assistant", "content": ""}))
        event = first
        while True:
            if isinstance(event, TextDelta):
                yield _sse(delta({"content": event.text}))
            else:
                yield _sse(delta({}, event.reason))
                if body.stream_options and body.stream_options.include_usage:
                    yield _sse(chunk([], usage=_usage(event)))
                yield _sse("[DONE]")
                return
            event = await anext(events)
    except ProviderError as error:
        # Headers are already sent, so report the failure in-band and never fabricate a [DONE].
        yield _sse(_error_payload(error))
    finally:
        await events.aclose()


def _usage(event: Finished) -> dict:
    return {
        "prompt_tokens": event.prompt_tokens,
        "completion_tokens": event.completion_tokens,
        "total_tokens": event.prompt_tokens + event.completion_tokens,
    }
