import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator

import httpx
import pytest
from lrl_gateway.app import create_app
from lrl_gateway.main import create_app_from_env
from lrl_gateway.models import ChatCompletionRequest
from lrl_gateway.providers.base import Finished, ProviderEvent, TextDelta
from lrl_gateway.providers.mock import MockConfig, MockProvider

MESSAGES = [{"role": "user", "content": "hello there"}]


def client_for(provider=None, timeout: float = 30) -> httpx.AsyncClient:
    app = create_app({"mock": provider or MockProvider()}, first_token_timeout_seconds=timeout)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def post(client: httpx.AsyncClient, **body) -> httpx.Response:
    return await client.post("/v1/chat/completions", json={"model": "mock", "messages": MESSAGES, **body})


def events(response: httpx.Response) -> list:
    lines = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    return [line if line == "[DONE]" else json.loads(line) for line in lines]


async def test_non_streaming_completion() -> None:
    async with client_for() as client:
        body = (await post(client)).json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"] == {
        "role": "assistant",
        "content": "This is a response from the mock provider.",
    }
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"] == {"prompt_tokens": 2, "completion_tokens": 8, "total_tokens": 10}


async def test_streaming_format() -> None:
    async with client_for() as client:
        response = await post(client, stream=True)
    assert response.headers["content-type"].startswith("text/event-stream")
    parsed = events(response)
    assert parsed[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    assert parsed[-1] == "[DONE]"
    assert parsed[-2]["choices"][0]["finish_reason"] == "stop"
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in parsed[:-1])
    assert text == "This is a response from the mock provider."
    assert all("usage" not in c for c in parsed[:-1])


async def test_stream_usage_when_requested() -> None:
    async with client_for() as client:
        parsed = events(await post(client, stream=True, stream_options={"include_usage": True}))
    assert parsed[-2]["choices"] == []
    assert parsed[-2]["usage"]["total_tokens"] == 10


@pytest.mark.parametrize(
    "body",
    [{"frequency_penalty": 1}, {"tools": []}, {"temperature": 9}, {"messages": []}, {"model": ""}],
)
async def test_invalid_requests_return_clear_400(body: dict) -> None:
    async with client_for() as client:
        response = await post(client, **body)
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["type"] == "invalid_request_error"
    assert error["message"]


async def test_unknown_model() -> None:
    async with client_for() as client:
        response = await post(client, model="qwen")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_found"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    ("model", "status", "code"),
    [("mock:429", 429, "rate_limited"), ("mock:500", 502, "upstream_error"), ("mock:nope", 404, "model_not_found")],
)
async def test_failures_before_first_token_use_http_status(stream: bool, model: str, status: int, code: str) -> None:
    async with client_for() as client:
        response = await post(client, model=model, stream=stream)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_rate_limit_sets_retry_after() -> None:
    async with client_for() as client:
        assert (await post(client, model="mock:429")).headers["retry-after"] == "1"


@pytest.mark.parametrize("stream", [False, True])
async def test_first_token_timeout(stream: bool) -> None:
    async with client_for(timeout=0.02) as client:
        response = await post(client, model="mock:timeout", stream=stream)
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "first_token_timeout"


async def test_mid_stream_failure_reports_error_without_done() -> None:
    async with client_for() as client:
        parsed = events(await post(client, model="mock:disconnect", stream=True))
    assert parsed[-1]["error"]["code"] == "upstream_disconnected"
    assert "[DONE]" not in parsed
    assert "".join(c["choices"][0]["delta"].get("content", "") for c in parsed[:-1]) == "This is"


async def test_non_streaming_mid_response_failure_is_an_error() -> None:
    async with client_for() as client:
        response = await post(client, model="mock:disconnect")
    assert response.status_code == 502
    assert "choices" not in response.json()


async def test_mock_timing_is_configurable() -> None:
    provider = MockProvider(MockConfig(time_to_first_token_seconds=0.05, tokens_per_second=100, reply="a b c"))
    request = ChatCompletionRequest(model="mock", messages=MESSAGES)
    start = time.perf_counter()
    stream = provider.stream(request)
    assert await anext(stream) == TextDelta("a")
    first = time.perf_counter() - start
    rest = [event async for event in stream]
    assert first >= 0.05
    assert time.perf_counter() - start >= 0.07
    assert rest[-1] == Finished("stop", 2, 3)


class EndlessProvider:
    def __init__(self) -> None:
        self.cancelled = threading.Event()

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ProviderEvent]:
        try:
            while True:
                yield TextDelta("x")
                await asyncio.sleep(0.01)
        finally:
            self.cancelled.set()


def test_client_disconnect_cancels_upstream(serve) -> None:
    provider = EndlessProvider()
    url = serve(create_app({"mock": provider}))
    body = {"model": "mock", "messages": MESSAGES, "stream": True}
    with httpx.stream("POST", f"{url}/v1/chat/completions", json=body) as response:
        next(response.iter_lines())
    assert provider.cancelled.wait(3)


async def test_env_factory_serves_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEWAY_FIRST_TOKEN_TIMEOUT_SECONDS", "1")
    transport = httpx.ASGITransport(app=create_app_from_env())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await post(client)).status_code == 200
