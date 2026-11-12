"""Helpers for talking to Rithmic's R|Protocol API.

Bindings are generated from a local kit by scripts/gen_rithmic_bindings.sh and
are never committed. R|Protocol frames are plain protobuf with no length prefix.
"""

import importlib
import os
import ssl
import sys
from pathlib import Path
from types import ModuleType


class RithmicKitMissing(RuntimeError):
    """The local Rithmic kit or generated bindings are not available."""


def bindings_dir() -> Path:
    return Path(os.environ.get("RITHMIC_BINDINGS_DIR", "rithmic_kit/gen")).resolve()


def binding(name: str) -> ModuleType:
    directory = bindings_dir()
    if not (directory / f"{name}.py").exists():
        raise RithmicKitMissing(f"{name} not found in {directory}; run scripts/gen_rithmic_bindings.sh")
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    return importlib.import_module(name)


def tls_context() -> ssl.SSLContext:
    kit = os.environ.get("RITHMIC_KIT_DIR")
    if not kit:
        raise RithmicKitMissing("RITHMIC_KIT_DIR is not set")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(Path(kit) / "etc" / "rithmic_ssl_cert_auth_params")
    context.check_hostname = False
    return context
