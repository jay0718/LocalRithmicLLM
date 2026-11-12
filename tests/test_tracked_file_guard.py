import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_tracked_files.py"


def run_guard(repo: Path, tracked: str) -> subprocess.CompletedProcess[str]:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    path = repo / tracked
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    subprocess.run(["git", "add", "-f", tracked], cwd=repo, check=True)
    return subprocess.run([sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True)


@pytest.mark.parametrize(
    "tracked",
    ["proto/login.proto", "gen/login_pb2.py", "etc/rithmic_ssl_cert_auth_params", ".env", "svc/.env.local", "a.pem"],
)
def test_guard_rejects_sensitive_files(tmp_path: Path, tracked: str) -> None:
    result = run_guard(tmp_path, tracked)
    assert result.returncode == 1
    assert tracked in result.stderr


@pytest.mark.parametrize("tracked", [".env.example", "services/x/.env.example", "README.md"])
def test_guard_allows_safe_files(tmp_path: Path, tracked: str) -> None:
    assert run_guard(tmp_path, tracked).returncode == 0
