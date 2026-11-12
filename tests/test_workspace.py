import importlib

import pytest


@pytest.mark.parametrize("service", ["collector", "console", "gateway", "gex", "pipeline"])
def test_service_imports_shared_package(service: str) -> None:
    assert f"lrl-{service}" == importlib.import_module(f"lrl_{service}").SERVICE_NAME
