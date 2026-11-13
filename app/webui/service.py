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

import asyncio
import ipaddress
import json
import os
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

    # ---------- bilibili discovery (needs login credentials) ----------

    _credential_cache: dict[str, Any] = {"credential": None, "uid": 0, "loaded_at": 0.0}

    async def _login_credential(self, ttl_seconds: float = 300.0):
        """Load and verify the Bilibili credential, cached briefly.

        Discovery endpoints need the login cookie; the daemon owns the
        long-lived session but the WebUI process can read the same
        ``cookie.json`` read-only.
        """
        import time

        from app.core.auth import check_cookie

        cache = self._credential_cache
        now = time.time()
        if cache["credential"] is not None and now - cache["loaded_at"] < ttl_seconds:
            return cache["credential"], cache["uid"]
        cookie_path = self.load_raw_config().get("system", {}).get("cookie_path")
        if not cookie_path:
            raise command_error("配置中缺少 cookie_path", status=503)
        credential, uid = await check_cookie(cookie_path)
        if not credential:
            raise command_error("登录凭据不可用，请先完成扫码登录", status=503)
        cache["credential"] = credential
        cache["uid"] = uid
        cache["loaded_at"] = now
        return credential, uid

    async def discover_favorites(self) -> dict[str, Any]:
        """全部视频收藏夹（名称 + id + 数量），供设置页自动填充。"""
        from app.core.parser import BiliParser, SyncFetchError

        credential, uid = await self._login_credential()
        parser = BiliParser(credential, uid=uid)
        try:
            favorites = await parser.get_user_favorite_lists()
        except SyncFetchError as exc:
            raise command_error(f"获取收藏夹失败: {exc}", status=503) from exc
        return {"favorites": favorites}

    async def discover_collections(self, mid: int | None = None) -> dict[str, Any]:
        """指定 UP 主（缺省登录账号）的全部合集/系列。"""
        from app.core.parser import BiliParser, SyncFetchError

        credential, uid = await self._login_credential()
        target = int(mid) if mid else uid
        parser = BiliParser(credential, uid=uid)
        try:
            collections = await parser.get_user_collections(target)
        except SyncFetchError as exc:
            raise command_error(f"获取合集失败: {exc}", status=503) from exc
        return {"collections": collections}

    # ---------- account login (qr code + status) ----------

    #: Active qr-login session. One at a time: creating a new qr code
    #: replaces the previous session, mirroring the CLI behaviour.
    _login_session: dict[str, Any] = {
        "qrcode_key": None,
        "created_at": 0.0,
        "state": "idle",
    }
    #: Session validity window, matching login.py's default timeout.
    LOGIN_SESSION_TTL = 180.0
    _login_status_cache: dict[str, Any] = {"result": None, "loaded_at": 0.0}

    async def login_qrcode_create(self) -> dict[str, Any]:
        """申请一个新的扫码登录会话，返回二维码图片（data URL）。"""
        import base64
        import io
        import time

        from app.core.bili_login import create_web_qrcode

        qrcode_key, url = await create_web_qrcode()
        import qrcode

        buffer = io.BytesIO()
        image = qrcode.QRCode()
        image.add_data(url)
        image.make_image().save(buffer)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        now = time.time()
        self._login_session.update(
            {
                "qrcode_key": qrcode_key,
                "created_at": now,
                "state": "waiting",
            }
        )
        return {
            "qrcode_key": qrcode_key,
            "qr_image": f"data:image/png;base64,{encoded}",
            "expires_in": int(self.LOGIN_SESSION_TTL),
        }

    async def login_qrcode_poll(self, key: str) -> dict[str, Any]:
        """查询一次扫码登录状态；登录完成时把凭据写入 cookie 路径。"""
        import time

        from app.core.bili_login import credential_is_usable, poll_qrcode

        session = self._login_session
        if not key or session.get("qrcode_key") != key:
            raise command_error("二维码会话不存在或已失效，请重新生成", status=422)
        created = float(session.get("created_at") or 0.0)
        if time.time() - created > self.LOGIN_SESSION_TTL:
            self._reset_login_session("expired")
            return {"status": "expired"}
        state, credential = await poll_qrcode(key)
        if state in {"waiting", "scanned", "confirmed"}:
            # 未扫码 / 已扫码 / 已确认：都是进行中，继续等待下一轮。
            session["state"] = state
            label = {
                "waiting": "等待扫码中…",
                "scanned": "已扫码，请在手机上确认",
                "confirmed": "已确认，正在完成登录",
            }[state]
            return {"status": state, "message": label}
        if state == "expired":
            self._reset_login_session("expired")
            return {"status": "expired"}
        if state == "done" and credential is not None and credential_is_usable(credential):
            cookie_path = self.load_raw_config().get("system", {}).get("cookie_path")
            if not cookie_path:
                raise command_error("配置中缺少 cookie_path", status=503)
            self._save_credential(credential, cookie_path)
            # 让 discover/status 的凭据缓存立即失效，避免 300s 内读到旧凭据。
            self._credential_cache["loaded_at"] = 0.0
            self._credential_cache["credential"] = None
            self._login_status_cache["loaded_at"] = 0.0
            account = await self.login_status(use_cache=False)
            self._reset_login_session("done")
            return {
                "status": "done",
                "account": account.get("account"),
            }
        if state == "done":
            # ticket 交换失败等异常场景：凭据不可用。
            self._reset_login_session("failed")
            return {"status": "expired", "message": "登录回调凭据无效，请重新扫码"}
        self._reset_login_session("failed")
        return {"status": "expired", "message": "登录流程异常，请重新扫码"}

    async def login_status(self, use_cache: bool = True) -> dict[str, Any]:
        """检测当前 B 站登录状态，返回账号昵称与 UID。"""
        import os
        import time

        from bilibili_api import user as bili_user

        from app.core.auth import check_cookie, is_auth_failure

        cache = self._login_status_cache
        now = time.time()
        if use_cache and cache["result"] is not None and now - cache["loaded_at"] < 60.0:
            return cache["result"]

        cookie_path = self.load_raw_config().get("system", {}).get("cookie_path")
        if not cookie_path or not os.path.exists(cookie_path):
            result = {"logged_in": False, "reason": "未登录"}
            cache.update({"result": result, "loaded_at": now})
            return result
        try:
            credential, uid = await check_cookie(cookie_path)
        except Exception as exc:  # 网络抖动等临时错误按未知状态处理
            if is_auth_failure(exc):
                result = {"logged_in": False, "reason": "登录凭据已失效，请重新扫码"}
            else:
                result = {"logged_in": False, "reason": f"状态检测失败: {exc}"}
            cache.update({"result": result, "loaded_at": now})
            return result
        if not credential:
            result = {"logged_in": False, "reason": "登录凭据已失效，请重新扫码"}
            cache.update({"result": result, "loaded_at": now})
            return result
        name = None
        try:
            info = await bili_user.get_self_info(credential)
            name = str(info.get("name") or "")
        except Exception:
            name = None
        result = {
            "logged_in": True,
            "account": {"name": name or f"UID {uid}", "uid": int(uid or 0)},
        }
        cache.update({"result": result, "loaded_at": now})
        return result

    def _save_credential(self, credential: Any, cookie_path: str) -> None:
        """把扫码得到的凭据原子写入 cookie 路径（字段与 login.py 一致）。"""
        from app.core.secure_file import atomic_write_text

        if isinstance(credential, dict):
            source = credential
        else:
            source = credential.get_cookies() if hasattr(credential, "get_cookies") else {}
        fields = {
            "sessdata": str(source.get("sessdata") or ""),
            "bili_jct": str(source.get("bili_jct") or ""),
            "buvid3": str(source.get("buvid3") or ""),
            "dedeuserid": str(source.get("dedeuserid") or ""),
            "ac_time_value": str(source.get("ac_time_value") or ""),
        }
        atomic_write_text(cookie_path, json.dumps(fields, ensure_ascii=False, indent=4) + "\n")

    def _reset_login_session(self, state: str) -> None:
        self._login_session.update(
            {"qrcode_key": None, "created_at": 0.0, "state": state}
        )

    # ---------- quality audit ----------

    async def run_quality_audit(self, limit: int = 2000) -> dict[str, Any]:
        """审计已下载视频的清晰度：本地 info.json vs 源端可用最高。

        默认覆盖全部已归档视频（当前库通常一两千个），逐个探测源端。
        只产出证据清单，不做任何删除；清除由用户在 WebUI 确认后经
        purge_low_quality 命令由核心执行（daemon 侧再二次校验）。
        """
        from app.core.quality_audit import audit_asset, probe_source_height, read_local_height

        credential, uid = await self._login_credential()
        database = self._database()
        total_videos = database.scalar(
            "SELECT COUNT(*) FROM assets "
            "WHERE type='video' AND status=0 AND path IS NOT NULL AND path != ''"
        )
        rows = database.query(
            "SELECT bvid, title, path, p_count FROM assets "
            "WHERE type='video' AND status=0 AND path IS NOT NULL AND path != '' "
            "ORDER BY last_check DESC LIMIT ?",
            [max(1, min(int(limit), 5000))],
        )
        download_root = self.download_root()
        downgraded: list[dict[str, Any]] = []
        skipped = 0
        probed = 0
        consecutive_failures = 0
        for row in rows:
            asset_dir = Path(os.fspath(row["path"]))
            if not asset_dir.is_absolute():
                asset_dir = self.project_root / asset_dir
            resolved = asset_dir.resolve()
            if not resolved.is_relative_to(download_root):
                skipped += 1
                continue
            local_height = read_local_height(resolved, row["p_count"] or 1)
            if local_height is None:
                skipped += 1
                continue
            source_height = await probe_source_height(str(row["bvid"]), credential)
            probed += 1
            if source_height is None:
                consecutive_failures += 1
                # 连续失败说明被风控限流：打印提示并放慢节奏，避免整轮全部空探测。
                if consecutive_failures % 20 == 0:
                    print(
                        f"[!] 清晰度审计：已连续 {consecutive_failures} 个源端探测失败"
                        "（可能触发 B 站风控限流），后续仍会继续尝试。"
                    )
                await asyncio.sleep(2.0)
                skipped += 1
                continue
            consecutive_failures = 0
            # 正常节奏限速：每个探测间隔 1.5 秒，1425 个约 35 分钟。
            await asyncio.sleep(1.5)
            verdict = audit_asset(local_height, source_height)
            if verdict.get("downgraded"):
                downgraded.append(
                    {
                        "bvid": row["bvid"],
                        "title": row["title"],
                        "local_height": local_height,
                        "source_height": source_height,
                    }
                )
        return {
            "downgraded": downgraded,
            "skipped_count": skipped,
            "audited_count": len(rows),
            "probed_count": probed,
            "total_videos": int(total_videos or 0),
        }


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
