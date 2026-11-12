import threading
import time
from collections.abc import Callable, Iterator

import pytest
import uvicorn
from fastapi import FastAPI


@pytest.fixture
def serve() -> Iterator[Callable[[FastAPI], str]]:
    """Run an app on a real local socket and return its base URL."""
    servers: list[tuple[uvicorn.Server, threading.Thread]] = []

    def start(app: FastAPI) -> str:
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.time() + 5
        while not server.started:
            assert time.time() < deadline, "server did not start"
            time.sleep(0.01)
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"

    yield start
    for server, thread in servers:
        server.should_exit = True
        thread.join(timeout=5)
