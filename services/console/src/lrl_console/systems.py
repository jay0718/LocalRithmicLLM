"""The list of Rithmic systems (firms), fetched live with a cached fallback."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import websockets
from lrl_common.rithmic import binding, tls_context

from .store import Store

log = logging.getLogger(__name__)

REQUEST_SYSTEM_INFO = 16
FetchSystems = Callable[[], Awaitable[list[str]]]


class SystemsUnavailable(Exception):
    """No live list could be fetched and none has been cached."""


@dataclass(frozen=True)
class SystemList:
    names: list[str]
    cached: bool
    fetched_at: float


async def fetch_rithmic_systems(uri: str, timeout_seconds: float = 10) -> list[str]:
    """Ask Rithmic which systems exist. Sends no credentials."""
    request_module = binding("request_rithmic_system_info_pb2")
    response_module = binding("response_rithmic_system_info_pb2")
    ssl_context = tls_context() if uri.startswith("wss://") else None
    async with websockets.connect(uri, ssl=ssl_context, open_timeout=timeout_seconds) as ws:
        request = request_module.RequestRithmicSystemInfo()
        request.template_id = REQUEST_SYSTEM_INFO
        await ws.send(request.SerializeToString())
        response = response_module.ResponseRithmicSystemInfo()
        response.ParseFromString(await asyncio.wait_for(ws.recv(), timeout_seconds))
    if list(response.rp_code)[:1] != ["0"]:
        raise RuntimeError(f"Rithmic rejected the system list request: {list(response.rp_code)}")
    return list(response.system_name)


class SystemCatalog:
    def __init__(
        self, fetch: FetchSystems, store: Store, ttl_seconds: float, clock: Callable[[], float] = time.time
    ) -> None:
        self._fetch = fetch
        self._store = store
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = asyncio.Lock()

    async def get(self) -> SystemList:
        async with self._lock:
            saved = self._store.load_systems()
            if saved and self._clock() - saved[1] < self._ttl:
                return SystemList(saved[0], cached=False, fetched_at=saved[1])
            try:
                names = await self._fetch()
            except Exception as error:
                log.warning("Could not fetch the Rithmic system list: %s", type(error).__name__)
                if saved:
                    return SystemList(saved[0], cached=True, fetched_at=saved[1])
                raise SystemsUnavailable from error
            fetched_at = self._clock()
            self._store.save_systems(names, fetched_at)
            return SystemList(names, cached=False, fetched_at=fetched_at)


def is_test_system(name: str) -> bool:
    return "test" in name.lower()
