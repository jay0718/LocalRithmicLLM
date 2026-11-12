"""Exercises real bindings against a local server. Skipped without the Rithmic kit."""

import pytest
import websockets
from lrl_common.rithmic import RithmicKitMissing, binding
from lrl_console.systems import fetch_rithmic_systems


@pytest.fixture
def bindings():
    try:
        return binding("request_rithmic_system_info_pb2"), binding("response_rithmic_system_info_pb2")
    except RithmicKitMissing:
        pytest.skip("Rithmic kit bindings are not available")


async def test_fetch_uses_plain_protobuf_frames(bindings) -> None:
    request_module, response_module = bindings

    async def handler(ws) -> None:
        frame = await ws.recv()
        request = request_module.RequestRithmicSystemInfo()
        request.ParseFromString(frame)
        assert request.template_id == 16
        response = response_module.ResponseRithmicSystemInfo()
        response.template_id = 17
        response.rp_code.append("0")
        response.system_name.extend(["Apex", "Bulenox"])
        await ws.send(response.SerializeToString())

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        assert await fetch_rithmic_systems(f"ws://127.0.0.1:{port}") == ["Apex", "Bulenox"]
