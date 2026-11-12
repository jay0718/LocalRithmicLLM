"""The official OpenAI Python SDK against a real gateway server."""

import openai
import pytest
from lrl_gateway.app import create_app
from lrl_gateway.providers.mock import MockProvider

REPLY = "This is a response from the mock provider."
MESSAGES = [{"role": "user", "content": "hello there"}]


@pytest.fixture
def sdk(serve) -> openai.OpenAI:
    url = serve(create_app({"mock": MockProvider()}, first_token_timeout_seconds=0.2))
    return openai.OpenAI(base_url=f"{url}/v1", api_key="unused", max_retries=0)


def test_non_streaming(sdk: openai.OpenAI) -> None:
    completion = sdk.chat.completions.create(model="mock", messages=MESSAGES)
    assert completion.choices[0].message.content == REPLY
    assert completion.usage.total_tokens == 10


def test_streaming(sdk: openai.OpenAI) -> None:
    chunks = list(
        sdk.chat.completions.create(
            model="mock", messages=MESSAGES, stream=True, stream_options={"include_usage": True}
        )
    )
    text = "".join(c.choices[0].delta.content or "" for c in chunks if c.choices)
    assert text == REPLY
    assert chunks[-1].usage.completion_tokens == 8


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("mock:429", openai.RateLimitError),
        ("mock:500", openai.InternalServerError),
        ("mock:timeout", openai.InternalServerError),
        ("unknown", openai.NotFoundError),
    ],
)
def test_errors_map_to_sdk_exceptions(sdk: openai.OpenAI, model: str, expected: type[Exception]) -> None:
    with pytest.raises(expected):
        sdk.chat.completions.create(model=model, messages=MESSAGES)


def test_mid_stream_error_raises(sdk: openai.OpenAI) -> None:
    with pytest.raises(openai.APIError):
        list(sdk.chat.completions.create(model="mock:disconnect", messages=MESSAGES, stream=True))
