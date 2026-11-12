"""SQLite storage for connections and the cached firm list.

Credentials live in their own small database, so they share no failure modes
or access paths with market data in Postgres.
"""

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

MIGRATIONS = (
    """
    CREATE TABLE connections (
        id INTEGER PRIMARY KEY,
        system_name TEXT NOT NULL,
        username TEXT NOT NULL,
        password_ciphertext BLOB NOT NULL,
        status TEXT NOT NULL DEFAULT 'untested',
        last_checked_at REAL,
        created_at REAL NOT NULL,
        UNIQUE (system_name, username)
    );
    CREATE TABLE system_cache (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        names TEXT NOT NULL,
        fetched_at REAL NOT NULL
    );
    """,
)


class DuplicateConnection(Exception):
    pass


@dataclass(frozen=True)
class Connection:
    """A stored connection. Deliberately has no password field."""

    id: int
    system_name: str
    username: str
    status: str
    last_checked_at: float | None
    created_at: float


_COLUMNS = "id, system_name, username, status, last_checked_at, created_at"


class Store:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()
        path.chmod(0o600)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self._path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _migrate(self) -> None:
        with self._db() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
                db.executescript(script)
                db.execute(f"PRAGMA user_version = {number}")

    def create(self, system_name: str, username: str, ciphertext: bytes) -> Connection:
        try:
            with self._db() as db:
                cursor = db.execute(
                    "INSERT INTO connections (system_name, username, password_ciphertext, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (system_name, username, ciphertext, time.time()),
                )
                connection_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            raise DuplicateConnection from None
        return self.get(connection_id)

    def all(self) -> list[Connection]:
        with self._db() as db:
            rows = db.execute(f"SELECT {_COLUMNS} FROM connections ORDER BY id").fetchall()
        return [Connection(*row) for row in rows]

    def get(self, connection_id: int) -> Connection | None:
        with self._db() as db:
            row = db.execute(f"SELECT {_COLUMNS} FROM connections WHERE id = ?", (connection_id,)).fetchone()
        return Connection(*row) if row else None

    def update(
        self, connection_id: int, system_name: str | None, username: str | None, ciphertext: bytes | None
    ) -> Connection | None:
        """Change the given fields. A new login resets the connection to untested."""
        try:
            with self._db() as db:
                db.execute(
                    "UPDATE connections SET system_name = COALESCE(?, system_name),"
                    " username = COALESCE(?, username),"
                    " password_ciphertext = COALESCE(?, password_ciphertext),"
                    " status = 'untested', last_checked_at = NULL WHERE id = ?",
                    (system_name, username, ciphertext, connection_id),
                )
        except sqlite3.IntegrityError:
            raise DuplicateConnection from None
        return self.get(connection_id)

    def delete(self, connection_id: int) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM connections WHERE id = ?", (connection_id,)).rowcount > 0

    def password_ciphertext(self, connection_id: int) -> bytes | None:
        with self._db() as db:
            row = db.execute("SELECT password_ciphertext FROM connections WHERE id = ?", (connection_id,)).fetchone()
        return row[0] if row else None

    def save_systems(self, names: list[str], fetched_at: float) -> None:
        with self._db() as db:
            db.execute(
                "INSERT INTO system_cache (id, names, fetched_at) VALUES (1, ?, ?)"
                " ON CONFLICT (id) DO UPDATE SET names = excluded.names, fetched_at = excluded.fetched_at",
                (json.dumps(names), fetched_at),
            )

    def load_systems(self) -> tuple[list[str], float] | None:
        with self._db() as db:
            row = db.execute("SELECT names, fetched_at FROM system_cache WHERE id = 1").fetchone()
        return (json.loads(row[0]), row[1]) if row else None
