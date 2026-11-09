"""Where the service reads from: the database, the download root and runtime.json.

The WebUI never writes any of these. The database is opened read-only and
`runtime.json` is written by the daemon, not by the panel.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable


class ReadOnlyDatabase:
    """A short-lived SQLite reader that can never create or migrate a database."""

    def __init__(self, path: os.PathLike[str] | str, *, timeout_ms: int = 5000):
        self.path = Path(path)
        self.timeout_ms = int(timeout_ms)

    def connect(self) -> sqlite3.Connection:
        uri = f"{self.path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=self.timeout_ms / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={self.timeout_ms}")
        return connection

    def query(self, sql: str, parameters: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(sql, tuple(parameters)).fetchall()

    def scalar(self, sql: str, parameters: Iterable[Any] = ()) -> Any:
        with self.connect() as connection:
            return connection.execute(sql, tuple(parameters)).fetchone()[0]


class RuntimeMixin:
    """Paths and read-only access to the daemon's published state."""

    def database_path(self) -> Path:
        if self._db_path_override:
            return self._db_path_override
        raw_config = self.load_raw_config()
        configured = raw_config.get("system", {}).get("db_path")
        if not configured:
            raise ValueError("未配置数据库路径")
        path = Path(os.fspath(configured))
        return (self.config_path.parent / path).resolve() if not path.is_absolute() else path.resolve()

    def download_root(self) -> Path:
        raw_config = self.load_raw_config()
        configured = raw_config.get("system", {}).get("download_path")
        if not configured:
            return (self.config_path.parent / "downloads").resolve()
        path = Path(os.fspath(configured))
        return (self.config_path.parent / path).resolve() if not path.is_absolute() else path.resolve()

    def _database(self) -> ReadOnlyDatabase:
        return ReadOnlyDatabase(self.database_path())

    def runtime(self) -> dict[str, Any]:
        path = self.database_path().parent / "runtime.json"
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}


__all__ = ["ReadOnlyDatabase", "RuntimeMixin"]
