import logging
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from lrl_common.rithmic import RithmicKitMissing
from lrl_console.app import create_app
from lrl_console.crypto import PasswordCipher
from lrl_console.settings import ConfigError, Settings
from lrl_console.store import Store
from lrl_console.systems import SystemCatalog, SystemsUnavailable, fetch_rithmic_systems

TOKEN = "admin-token"
PASSWORD = "sup3r-s3cret-pw"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def settings(tmp_path: Path, token: str = TOKEN) -> Settings:
    return Settings(admin_token=token, secret_key=Fernet.generate_key().decode(), db_path=tmp_path / "c.db")


async def two_systems() -> list[str]:
    return ["Apex", "Rithmic Test"]


@pytest.fixture
def config(tmp_path: Path) -> Settings:
    return settings(tmp_path)


@pytest.fixture
def client(config: Settings) -> TestClient:
    return TestClient(create_app(config, two_systems), headers=AUTH, raise_server_exceptions=False)


def add(client: TestClient, username: str = "trader") -> dict:
    response = client.post("/connections", json={"system_name": "Apex", "username": username, "password": PASSWORD})
    assert response.status_code == 201
    return response.json()


def test_cipher_round_trips_and_hides_plaintext() -> None:
    cipher = PasswordCipher(Fernet.generate_key().decode())
    ciphertext = cipher.encrypt(PASSWORD)
    assert PASSWORD.encode() not in ciphertext
    assert cipher.decrypt(ciphertext) == PASSWORD


@pytest.mark.parametrize("key", [None, "not-a-key"])
def test_refuses_to_start_without_valid_key(monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
    if key:
        monkeypatch.setenv("CONSOLE_SECRET_KEY", key)
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_settings_repr_has_no_secrets(config: Settings) -> None:
    assert TOKEN not in repr(config) and config.secret_key not in repr(config)


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    Store(tmp_path / "m.db").create("Apex", "u", b"c")
    assert len(Store(tmp_path / "m.db").all()) == 1


def test_database_file_is_owner_only(config: Settings, client: TestClient) -> None:
    assert config.db_path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("path", ["/systems", "/connections", "/connections/1"])
def test_requires_token(config: Settings, path: str) -> None:
    anonymous = TestClient(create_app(config, two_systems))
    assert anonymous.get(path).status_code == 401
    assert anonymous.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_fails_closed_when_token_unset(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path, token=""), two_systems))
    assert client.get("/connections").status_code == 503
    assert client.get("/connections", headers={"Authorization": "Bearer "}).status_code == 503


def test_systems_flags_test_systems(client: TestClient) -> None:
    body = client.get("/systems").json()
    assert body["systems"] == [{"name": "Apex", "is_test": False}, {"name": "Rithmic Test", "is_test": True}]
    assert body["cached"] is False


class Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_catalog_uses_ttl_then_falls_back(tmp_path: Path) -> None:
    calls = 0
    fail = False

    async def fetch() -> list[str]:
        nonlocal calls
        calls += 1
        if fail:
            raise OSError
        return ["Apex"]

    clock = Clock()
    catalog = SystemCatalog(fetch, Store(tmp_path / "s.db"), 60, clock)
    assert (await catalog.get()).cached is False
    await catalog.get()
    assert calls == 1

    clock.now += 61
    fail = True
    result = await catalog.get()
    assert (result.names, result.cached, result.fetched_at) == (["Apex"], True, 1000.0)


async def test_catalog_raises_with_no_list(tmp_path: Path) -> None:
    async def fetch() -> list[str]:
        raise OSError

    with pytest.raises(SystemsUnavailable):
        await SystemCatalog(fetch, Store(tmp_path / "s.db"), 60).get()


def test_systems_returns_503_with_no_list(config: Settings) -> None:
    async def fail() -> list[str]:
        raise OSError

    assert TestClient(create_app(config, fail), headers=AUTH).get("/systems").status_code == 503


async def test_fetch_needs_the_kit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RITHMIC_BINDINGS_DIR", str(tmp_path))
    with pytest.raises(RithmicKitMissing):
        await fetch_rithmic_systems("ws://localhost:1")


def test_create_list_get_delete(client: TestClient) -> None:
    created = add(client)
    assert created["status"] == "untested"
    assert client.get("/connections").json() == [created]
    assert client.get(f"/connections/{created['id']}").json() == created
    assert client.delete(f"/connections/{created['id']}").status_code == 204
    assert client.get(f"/connections/{created['id']}").status_code == 404
    assert client.delete(f"/connections/{created['id']}").status_code == 404


def test_duplicate_connection_conflicts(client: TestClient) -> None:
    add(client)
    response = client.post("/connections", json={"system_name": "Apex", "username": "trader", "password": "x"})
    assert response.status_code == 409


def test_update_with_blank_password_keeps_old_one(config: Settings, client: TestClient) -> None:
    created = add(client)
    store, cipher = Store(config.db_path), PasswordCipher(config.secret_key)
    before = store.password_ciphertext(created["id"])
    response = client.put(f"/connections/{created['id']}", json={"username": "renamed", "password": ""})
    assert response.json()["username"] == "renamed"
    assert store.password_ciphertext(created["id"]) == before
    assert cipher.decrypt(before) == PASSWORD


def test_update_replaces_password(config: Settings, client: TestClient) -> None:
    created = add(client)
    client.put(f"/connections/{created['id']}", json={"password": "new-password"})
    store, cipher = Store(config.db_path), PasswordCipher(config.secret_key)
    assert cipher.decrypt(store.password_ciphertext(created["id"])) == "new-password"


def test_update_missing_connection(client: TestClient) -> None:
    assert client.put("/connections/99", json={"username": "x"}).status_code == 404


def test_update_conflict(client: TestClient) -> None:
    add(client, "one")
    second = add(client, "two")
    assert client.put(f"/connections/{second['id']}", json={"username": "one"}).status_code == 409


def test_passwords_never_reach_responses_logs_or_disk(
    config: Settings, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    created = add(client)
    responses = [
        client.get("/connections"),
        client.get(f"/connections/{created['id']}"),
        client.put(f"/connections/{created['id']}", json={"password": PASSWORD}),
        client.post("/connections", json={"system_name": "Apex", "username": "trader", "password": PASSWORD}),
        client.post("/connections", json={"system_name": "", "username": "", "password": PASSWORD}),
        client.post("/connections", json={"system_name": "Apex", "password": PASSWORD, "username": 5}),
    ]
    assert [r.status_code for r in responses] == [200, 200, 200, 409, 422, 422]
    for response in responses:
        assert PASSWORD not in response.text
        assert "ciphertext" not in response.text
    assert PASSWORD not in caplog.text
    assert PASSWORD.encode() not in config.db_path.read_bytes()
