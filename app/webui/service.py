"""Read-only service functions used by the WebUI API.

`WebService` is the facade the API layer talks to. The read paths live in
one mixin per query domain under `app/webui/queries/`:

    settings.py  the public configuration: read, validate, write
    assets.py    the asset list and the cover art lookup
    overview.py  the dashboard: counts, recent assets, free disk space
    runtime.py   the read-only database, the paths and runtime.json

This module keeps the pieces the API layer imports directly and the
command-channel methods that belong to the channel rather than to a query.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any

from app.core.commands import CommandError

from .queries.assets import AssetsMixin
from .queries.overview import OverviewMixin
from .queries.runtime import ReadOnlyDatabase, RuntimeMixin
from .queries.settings import (
    CONFIG_SCHEMA,
    ConfigValidationError,
    RevisionConflict,
    SettingsMixin,
    config_revision,
    public_config,
    validate_config_payload,
)


def command_error(message: str, status: int = 422):
    """Build a ``CommandError`` carrying an HTTP status for the API layer."""
    error = CommandError(message)
    error.status = status
    return error


def is_loopback_host(host: str) -> bool:
    value = (host or "").strip().lower()
    if value in {"localhost", "localhost.localdomain"}:
        return True
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


class WebService(
    SettingsMixin,
    AssetsMixin,
    OverviewMixin,
    RuntimeMixin,
):
    def __init__(
        self,
        *,
        project_root: Path,
        config_path: Path,
        db_path: Path | None = None,
        version: str,
    ):
        self.project_root = project_root.resolve()
        self.config_path = config_path.resolve()
        self._db_path_override = db_path.resolve() if db_path else None
        self.version = version

    # ---------- command channel ----------

    def command_channel(self):
        """Return a command channel next to the database, or raise.

        The WebUI never talks to the daemon directly: it appends a command to
        ``commands.json`` and lets the daemon pick it up on its next poll.
        """
        from app.core import commands as commands_module

        path = commands_module.commands_path(self.load_raw_config())
        if not path:
            raise command_error("当前数据库配置不支持命令通道", status=503)
        return commands_module.CommandChannel(path)

    def command_snapshot(self) -> dict[str, Any]:
        """Pending queue plus recent audit history, for the operator panel."""
        snapshot = self.command_channel().snapshot()
        from app.core import commands as commands_module

        return {
            "supported": list(commands_module.SUPPORTED_COMMANDS),
            **snapshot,
        }

    def submit_command(self, body: Any) -> dict[str, Any]:
        """Validate and queue one command, returning its queued record."""
        if not isinstance(body, dict):
            raise command_error("请求体必须是对象")
        name = body.get("command")
        if not isinstance(name, str) or not name.strip():
            raise command_error("缺少 command 字段")
        note = body.get("note", "")
        if note is not None and not isinstance(note, str):
            raise command_error("note 必须是字符串")
        channel = self.command_channel()
        return channel.enqueue(name.strip(), body.get("payload"), note=note or "")

    def command_status(self, command_id: str) -> dict[str, Any]:
        record = self.command_channel().command_status(command_id)
        if record is None:
            raise command_error("命令不存在", status=404)
        return record


__all__ = [
    "CONFIG_SCHEMA",
    "ConfigValidationError",
    "ReadOnlyDatabase",
    "RevisionConflict",
    "WebService",
    "command_error",
    "config_revision",
    "is_loopback_host",
    "public_config",
    "validate_config_payload",
]
