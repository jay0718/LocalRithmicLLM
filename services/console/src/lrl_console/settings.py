"""Console configuration, read from the environment."""

import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

DEFAULT_SYSTEMS_URI = "wss://rprotocol.rithmic.com:443"


class ConfigError(RuntimeError):
    """The console cannot start safely with the current configuration."""


@dataclass(frozen=True)
class Settings:
    admin_token: str
    secret_key: str
    db_path: Path
    systems_uri: str = DEFAULT_SYSTEMS_URI
    systems_ttl_seconds: float = 3600

    def __repr__(self) -> str:
        return f"Settings(db_path={self.db_path!r}, systems_uri={self.systems_uri!r})"

    @classmethod
    def from_env(cls) -> "Settings":
        secret_key = os.environ.get("CONSOLE_SECRET_KEY", "")
        if not secret_key:
            raise ConfigError("CONSOLE_SECRET_KEY must be set")
        try:
            Fernet(secret_key)
        except ValueError:
            raise ConfigError("CONSOLE_SECRET_KEY is not a valid Fernet key") from None
        return cls(
            admin_token=os.environ.get("CONSOLE_ADMIN_TOKEN", ""),
            secret_key=secret_key,
            db_path=Path(os.environ.get("CONSOLE_DB_PATH", "data/console.db")),
            systems_uri=os.environ.get("RITHMIC_SYSTEMS_URI", DEFAULT_SYSTEMS_URI),
        )
