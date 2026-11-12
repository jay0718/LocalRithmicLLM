"""Run with: uvicorn --factory lrl_gateway.main:create_app_from_env"""

import os

from fastapi import FastAPI

from .app import create_app
from .providers.mock import MockProvider


def create_app_from_env() -> FastAPI:
    timeout = float(os.environ.get("GATEWAY_FIRST_TOKEN_TIMEOUT_SECONDS", "30"))
    return create_app({"mock": MockProvider()}, first_token_timeout_seconds=timeout)
