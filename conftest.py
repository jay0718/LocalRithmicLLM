"""Fixtures shared by every test in the repo."""

import os

import pytest

ISOLATED_PREFIXES = ("RITHMIC_", "CONSOLE_", "GATEWAY_", "OLLAMA_")


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's local configuration out of tests."""
    for name in os.environ:
        if name.startswith(ISOLATED_PREFIXES):
            monkeypatch.delenv(name)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("LRL_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="needs the Compose stack; set LRL_INTEGRATION=1")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
