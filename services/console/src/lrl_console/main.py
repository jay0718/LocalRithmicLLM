"""Run with: uvicorn --factory lrl_console.main:create_app_from_env"""

from fastapi import FastAPI

from .app import create_app
from .settings import Settings


def create_app_from_env() -> FastAPI:
    return create_app(Settings.from_env())
