#!/usr/bin/env python3
"""Write each service's OpenAPI schema to web/openapi/ for the typed UI client."""

import json
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from lrl_console.app import create_app as console_app
from lrl_console.settings import Settings
from lrl_gateway.app import create_app as gateway_app
from lrl_gateway.providers.mock import MockProvider
from lrl_gex.app import create_app as gex_app
from lrl_gex.engine import EngineConfig
from lrl_gex.runtime import PRODUCTS, UnderlyingRuntime

OUT = Path(__file__).resolve().parent.parent / "web" / "openapi"


async def _no_systems() -> list[str]:
    return []


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(admin_token="x", secret_key=Fernet.generate_key().decode(), db_path=Path(tmp) / "c.db")
        apps = {
            "console": console_app(settings, _no_systems),
            "gex": gex_app({"ESZ6": UnderlyingRuntime(PRODUCTS["ES"], [], EngineConfig())}),
            "gateway": gateway_app({"mock": MockProvider()}),
        }
        for name, app in apps.items():
            (OUT / f"{name}.json").write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
