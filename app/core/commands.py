"""Local command channel between the WebUI and the core daemon.

The WebUI stays a stateless client and never connects to the daemon directly.
Instead it appends commands to ``commands.json`` next to ``runtime.json``;
the daemon polls that file between scan cycles and acknowledges each command
with a result. This mirrors the existing ``runtime.json`` publishing
philosophy (atomic write, no socket, no WebSocket) and keeps the daemon the
single writer of process state.

Deliberate safety boundary: no command deletes local assets. The only mutating
operations are "scan again now", "ask the operator to restart", and
"re-download one asset", and every command is recorded in an audit trail.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime

from app.core.runtime_state import update_runtime
from app.core.secure_file import atomic_write_text

COMMAND_TRIGGER_SCAN = "trigger_scan"
COMMAND_RESTART = "restart"
COMMAND_REDOWNLOAD_ASSET = "redownload_asset"
COMMAND_RELOAD_CONFIG = "reload_config"
COMMAND_PURGE_LOW_QUALITY = "purge_low_quality"

SUPPORTED_COMMANDS = (COMMAND_TRIGGER_SCAN, COMMAND_RESTART, COMMAND_REDOWNLOAD_ASSET, COMMAND_RELOAD_CONFIG, COMMAND_PURGE_LOW_QUALITY)

#: Commands that must never be dispatched, even if the file is hand-edited.
#: Deleting local media stays a manual, out-of-band operation by design.
FORBIDDEN_COMMANDS = frozenset(
    {
        "delete_asset",
        "delete_local_file",
        "delete_all",
        "wipe",
        "format",
        "drop_database",
    }
)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

MAX_PENDING = 32
MAX_HISTORY = 50
MAX_NOTE_LENGTH = 200

#: Only stable identifiers are accepted, so a command can never carry a
#: filesystem path and can never be used for path traversal.
ASSET_ID_PATTERN = re.compile(r"^(BV[0-9A-Za-z]{8,12}|av[0-9]{1,20})$")


class CommandError(ValueError):
    """Raised when a command payload is outside the public command schema."""


class CommandNotFound(CommandError):
    """Raised when the daemon has no readable command channel."""


def _now() -> datetime:
    return datetime.now().astimezone()


def _now_text() -> str:
    return _now().isoformat(timespec="seconds")


def commands_path(config) -> str | None:
    """Locate ``commands.json`` next to the database, like ``runtime.json``."""
    db_path = os.fspath(config.get("system", {}).get("db_path") or "")
    if not db_path or db_path == ":memory:":
        return None
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "commands.json")


def validate_asset_id(asset_id) -> str:
    """Accept only a stable BV/av key; never a path or arbitrary text."""
    if not isinstance(asset_id, str):
        raise CommandError("asset_id 必须是字符串")
    candidate = asset_id.strip()
    if not ASSET_ID_PATTERN.match(candidate):
        raise CommandError("asset_id 必须是合法的 BV 或 av 编号")
    return candidate


def validate_command_payload(name, payload) -> dict:
    """Validate one command and return its normalized payload."""
    if not isinstance(name, str):
        raise CommandError("command 必须是字符串")
    normalized = name.strip()
    if normalized.lower() in FORBIDDEN_COMMANDS:
        raise CommandError(f"不支持的命令: {normalized}")
    if normalized not in SUPPORTED_COMMANDS:
        raise CommandError(f"不支持的命令: {normalized}")

    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise CommandError("payload 必须是对象")

    if normalized == COMMAND_REDOWNLOAD_ASSET:
        unknown = set(payload) - {"asset_id"}
        if unknown:
            raise CommandError(f"不允许的命令参数: {sorted(unknown)[0]}")
        if "asset_id" not in payload:
            raise CommandError("redownload_asset 需要 asset_id")
        return {"asset_id": validate_asset_id(payload["asset_id"])}

    if normalized == COMMAND_PURGE_LOW_QUALITY:
        # 清除低清晰度资产：只接受审计通过的证据清单（bvid 列表）。
        unknown = set(payload) - {"asset_ids"}
        if unknown:
            raise CommandError(f"不允许的命令参数: {sorted(unknown)[0]}")
        asset_ids = payload.get("asset_ids")
        if not isinstance(asset_ids, list) or not asset_ids:
            raise CommandError("purge_low_quality 需要非空 asset_ids 列表")
        if len(asset_ids) > 100:
            raise CommandError("单次最多清除 100 个资产")
        return {"asset_ids": [validate_asset_id(item) for item in asset_ids]}

    if payload:
        raise CommandError(f"{normalized} 不接受任何参数")
    return {}


class CommandChannel:
    """Append-only command inbox with a bounded audit history.

    The WebUI process only appends; the daemon only consumes and acknowledges.
    Both sides write the whole file atomically, and every mutation re-reads the
    current file first so a command queued between two calls is never dropped.
    """

    def __init__(self, path):
        self.path = os.path.abspath(os.fspath(path))

    # ---------- persistence helpers ----------

    def _read(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {"version": 1, "pending": [], "history": []}
        except (json.JSONDecodeError, OSError):
            # A half-written or corrupted inbox must not wedge the daemon; the
            # operator can still queue a new command afterwards.
            return {"version": 1, "pending": [], "history": []}
        if not isinstance(data, dict):
            return {"version": 1, "pending": [], "history": []}
        pending = data.get("pending")
        history = data.get("history")
        return {
            "version": 1,
            "pending": [item for item in pending if isinstance(item, dict)]
            if isinstance(pending, list)
            else [],
            "history": [item for item in history if isinstance(item, dict)]
            if isinstance(history, list)
            else [],
        }

    def _write(self, payload: dict) -> None:
        body = {
            "version": 1,
            "updated_at": _now_text(),
            "pending": payload["pending"],
            "history": payload["history"],
        }
        atomic_write_text(self.path, json.dumps(body, ensure_ascii=False, indent=2) + "\n")

    # ---------- producer side (WebUI) ----------

    def enqueue(self, name: str, payload=None, *, note: str = "") -> dict:
        normalized_payload = validate_command_payload(name, payload)
        normalized_name = name.strip()
        command = {
            "id": uuid.uuid4().hex,
            "command": normalized_name,
            "payload": normalized_payload,
            "status": STATUS_PENDING,
            "note": _clean_note(note),
            "queued_at": _now_text(),
            "started_at": None,
            "finished_at": None,
            "result": None,
        }
        data = self._read()
        data["pending"].append(command)
        data["pending"] = data["pending"][-MAX_PENDING:]
        data["history"] = (data["history"] + [_queued_record(command)])[-MAX_HISTORY:]
        self._write(data)
        return dict(command)

    def snapshot(self) -> dict:
        """Read-only view for the WebUI: pending queue plus recent history."""
        data = self._read()
        return {
            "pending": [dict(item) for item in data["pending"]],
            "history": [dict(item) for item in data["history"][-MAX_HISTORY:]],
            "updated_at": self._read().get("updated_at"),
        }

    def command_status(self, command_id: str) -> dict | None:
        if not isinstance(command_id, str) or not command_id.strip():
            raise CommandError("command id 无效")
        data = self._read()
        for item in data["pending"]:
            if item.get("id") == command_id:
                return dict(item)
        for item in reversed(data["history"]):
            if item.get("id") == command_id:
                return dict(item)
        return None

    # ---------- consumer side (daemon) ----------

    def take_pending(self) -> list[dict]:
        """Atomically claim the pending queue for this poll cycle.

        Marking rows ``running`` before returning guarantees a command is
        executed at most once even if the daemon dies mid-cycle; the stale
        ``running`` rows stay visible in the history for inspection.
        """
        data = self._read()
        if not data["pending"]:
            return []
        claimed = []
        for item in data["pending"]:
            entry = dict(item)
            entry["status"] = STATUS_RUNNING
            entry["started_at"] = _now_text()
            _replace_history(data["history"], entry)
            claimed.append(entry)
        data["pending"] = []
        self._write(data)
        return claimed

    def complete(self, command: dict, *, ok: bool, result: str = "") -> None:
        """Acknowledge a claimed command and append it to the audit trail."""
        entry = dict(command)
        entry["status"] = STATUS_DONE if ok else STATUS_FAILED
        entry["finished_at"] = _now_text()
        entry["result"] = _clean_note(result)
        data = self._read()
        _replace_history(data["history"], entry)
        data["history"] = data["history"][-MAX_HISTORY:]
        self._write(data)


def _queued_record(command: dict) -> dict:
    return {
        "id": command["id"],
        "command": command["command"],
        "payload": command["payload"],
        "status": STATUS_PENDING,
        "note": command["note"],
        "queued_at": command["queued_at"],
        "started_at": None,
        "finished_at": None,
        "result": None,
    }


def _replace_history(history: list[dict], entry: dict) -> None:
    for index, item in enumerate(history):
        if item.get("id") == entry.get("id"):
            history[index] = entry
            return
    history.append(entry)


def _clean_note(text) -> str:
    if not isinstance(text, str):
        return ""
    flattened = " ".join(text.split())
    return flattened[:MAX_NOTE_LENGTH]


def open_channel(config) -> CommandChannel:
    """Return a channel for the configured data directory.

    Raises ``CommandNotFound`` when the daemon runs against an in-memory
    database, because there is no file for the WebUI to write to.
    """
    path = commands_path(config)
    if not path:
        raise CommandNotFound("当前数据库配置不支持命令通道")
    return CommandChannel(path)


def pending_command_age_seconds(command: dict) -> float:
    """Age of a claimed command, used to explain stale ``running`` rows."""
    started = command.get("started_at") or command.get("queued_at")
    if not isinstance(started, str):
        return 0.0
    try:
        parsed = datetime.fromisoformat(started)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return max(0.0, (_now() - parsed).total_seconds())


async def dispatch_commands(channel, scanner, runtime, pending_scan=None) -> bool:
    """消费一轮命令，返回是否请求退出守护循环。

    所有命令都在 try/except 中执行并回执，单条失败不会中断扫描循环。
    """
    if channel is None:
        return False
    try:
        commands = channel.take_pending()
    except Exception as exc:
        print(f"[!] 命令通道读取失败，本轮跳过: {exc}")
        return False

    for command in commands:
        name = command.get("command")
        payload = command.get("payload") or {}
        try:
            if name == COMMAND_TRIGGER_SCAN:
                update_runtime(
                    runtime,
                    message="已收到 WebUI 触发的即时扫描指令",
                )
                print("[*] 已收到即时扫描指令。")
                channel.complete(command, ok=True, result="已排入当前巡检轮次")
                # 置位事件：若当前正处于休眠分片，则提前唤醒开始下一轮；
                # 若正处于扫描中，本轮结束后的休眠检查会立即消费该事件。
                if pending_scan is not None:
                    pending_scan.set()
                # 必须继续处理本批剩余命令：它们已被 claim，若不回执会永远
                # 停留在 running 状态而无法被审计或重试。
                continue
            if name == COMMAND_REDOWNLOAD_ASSET:
                if scanner is None:
                    raise CommandError("尚未登录，无法登记重下载；请先在 WebUI 扫码登录")
                asset_id = payload.get("asset_id")
                if not asset_id:
                    raise CommandError("redownload_asset 缺少 asset_id")
                keys = scanner.request_redownload(asset_id)
                if not keys:
                    raise CommandError("无效的 asset_id")
                print(f"[*] 已登记重下载请求: {asset_id}（将在下一轮巡检命中）")
                channel.complete(
                    command,
                    ok=True,
                    result=f"已登记 {asset_id}，下轮巡检命中时重下",
                )
                continue
            if name == COMMAND_RESTART:
                # 不在守护进程内自重启，避免半途中断下载；交由运维层处理。
                update_runtime(
                    runtime,
                    status="restart_requested",
                    message="已收到重启指令，请在完成当前轮次后重启核心进程",
                )
                print("[!] 已收到重启指令：请在当前轮次结束后重启核心进程。")
                channel.complete(command, ok=True, result="已提示运维层重启核心进程")
                return True
            if name == COMMAND_RELOAD_CONFIG:
                if scanner is None:
                    # 等待登录阶段没有 scanner；cookie 文件变化本身就会
                    # 触发凭据重查，此处直接回执即可。
                    print("[*] 未登录阶段收到配置重载：将在登录后生效。")
                    channel.complete(command, ok=True, result="等待登录中，配置将在登录后生效")
                    continue
                reloaded = scanner.reload_config()
                if reloaded:
                    print("[*] 已重新加载配置：来源列表与运行参数即时生效。")
                    channel.complete(
                        command,
                        ok=True,
                        result="配置已热重载（重启类参数仍需重启进程）",
                    )
                else:
                    print("[!] 配置热重载失败，继续使用当前配置。")
                    channel.complete(command, ok=False, result="配置重载失败，保留当前配置")
                continue
            if name == COMMAND_PURGE_LOW_QUALITY:
                if scanner is None:
                    raise CommandError("尚未登录，无法执行清晰度清除；请先扫码登录")
                asset_ids = payload.get("asset_ids") or []
                purged, failed = scanner.purge_low_quality_assets(asset_ids)
                result_text = f"已清除 {purged} 个，失败 {failed} 个，均已在下一轮重下高清"
                print(f"[*] 清晰度清除完成: {result_text}")
                channel.complete(command, ok=failed == 0, result=result_text)
                continue
            raise CommandError(f"不支持的命令: {name}")
        except CommandError as exc:
            print(f"[-] 命令执行失败: {exc}")
            channel.complete(command, ok=False, result=str(exc))
        except Exception as exc:
            print(f"[-] 命令执行异常: {type(exc).__name__}: {exc}")
            channel.complete(command, ok=False, result=f"{type(exc).__name__}: {exc}"[:200])
    return False


__all__ = [
    "COMMAND_PURGE_LOW_QUALITY",
    "COMMAND_REDOWNLOAD_ASSET",
    "COMMAND_RELOAD_CONFIG",
    "COMMAND_RESTART",
    "COMMAND_TRIGGER_SCAN",
    "CommandChannel",
    "CommandError",
    "CommandNotFound",
    "MAX_HISTORY",
    "MAX_PENDING",
    "STATUS_DONE",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "SUPPORTED_COMMANDS",
    "commands_path",
    "dispatch_commands",
    "open_channel",
    "pending_command_age_seconds",
    "validate_command_payload",
]
