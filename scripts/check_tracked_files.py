#!/usr/bin/env python3
"""Fail if git tracks secrets or files from Rithmic's non-redistributable kit."""

import fnmatch
import subprocess
import sys

FORBIDDEN = ("*.proto", "*_pb2.py", "*_pb2.pyi", "*rithmic_ssl_cert_auth_params", "*.pem", "*.key", ".env", "*/.env")
FORBIDDEN_ENV_VARIANTS = (".env.*", "*/.env.*")
ALLOWED = (".env.example", "*/.env.example")


def is_forbidden(path: str) -> bool:
    if any(fnmatch.fnmatch(path, pattern) for pattern in ALLOWED):
        return False
    return any(fnmatch.fnmatch(path, pattern) for pattern in FORBIDDEN + FORBIDDEN_ENV_VARIANTS)


def main() -> int:
    tracked = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True, text=True).stdout
    violations = [path for path in tracked.split("\0") if path and is_forbidden(path)]
    for path in violations:
        print(f"Forbidden tracked file: {path}", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
