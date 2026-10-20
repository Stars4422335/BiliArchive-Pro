"""首次使用体验相关的测试（M4-可用性）。

覆盖验收实测发现的三个真实问题：
1. 登录凭据失效时，守护进程会带着死凭据空转整个休眠周期——应明确失败。
2. 临时故障（网络抖动）不应导致退出——公开视频仍可下载。
3. 核心引擎未运行时，WebUI 无法区分"没跑"与"空闲"——应给出明确信号。
"""

import asyncio
import json
import sqlite3

import pytest

import main
from app.webui.service import WebService


# ---------- 凭据失效识别 ----------


class _AuthError(Exception):
    """模拟 bilibili_api 的 ResponseCodeException：code 是整段 raw。"""

    def __init__(self, code, message):
        super().__init__(f"接口返回错误代码：{code}，信息：{message}。")
        self.code = code


def test_auth_failure_detected_from_response_code():
    exc = _AuthError({"code": -101, "message": "账号未登录", "ttl": 1}, "账号未登录")
    assert main._is_auth_failure(exc) is True


def test_auth_failure_detected_from_message():
    class _Plain(Exception):
        pass

    assert main._is_auth_failure(_Plain("SESSDATA 失效")) is True
    assert main._is_auth_failure(_Plain("登录已过期")) is True


def test_login_error_type_is_auth_failure():
    from bilibili_api.exceptions import LoginError

    assert main._is_auth_failure(LoginError("login required")) is True


def test_transient_failures_are_not_auth_failures():
    """网络抖动、超时、5xx 都不该被当成"凭据失效"。"""
    class _Plain(Exception):
        pass

    for message in (
        "Connection timed out",
        "ConnectError: 远程主机强迫关闭了一个现有的连接",
        "ReadTimeout",
        "Server error 500",
    ):
        assert main._is_auth_failure(_Plain(message)) is False, message


def test_non_auth_response_codes_are_not_auth_failures():
    """-400（请求错误）、-509（请求过于频繁）都不是鉴权问题。

    把它们算作鉴权失败会让守护进程在普通请求错误时也退出，
    并误导用户去重新登录——而重新登录解决不了请求错误。
    """
    for code, message in (
        (-400, "请求错误"),
        (-509, "请求过于频繁"),
        (-404, "无此项"),
    ):
        exc = _AuthError({"code": code, "message": message, "ttl": 1}, message)
        assert main._is_auth_failure(exc) is False, f"{code} 不应被视为鉴权失败"


def test_csrf_failure_counts_as_auth_failure():
    """-111 是 csrf 校验失败，csrf token 来自 cookie，属凭据问题。"""
    exc = _AuthError({"code": -111, "message": "csrf 校验失败", "ttl": 1}, "csrf 校验失败")

    assert main._is_auth_failure(exc) is True


# ---------- check_cookie 行为 ----------


def _write_cookie(tmp_path, **overrides):
    data = {
        "sessdata": "x" * 20,
        "bili_jct": "y" * 32,
        "buvid3": "z" * 20,
        "dedeuserid": "12345",
        "ac_time_value": "",
    }
    data.update(overrides)
    path = tmp_path / "cookie.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_check_cookie_returns_none_when_credential_expired(tmp_path, monkeypatch):
    """凭据确定失效时返回 (None, None)，让调用方终止而不是空转。"""
    cookie = _write_cookie(tmp_path)

    async def boom(_cred):
        raise _AuthError({"code": -101, "message": "账号未登录", "ttl": 1}, "账号未登录")

    monkeypatch.setattr(main.user, "get_self_info", boom)

    cred, uid = asyncio.run(main.check_cookie(cookie))
    assert cred is None
    assert uid is None


def test_check_cookie_keeps_credential_on_transient_failure(tmp_path, monkeypatch):
    """临时故障下仍返回凭据：公开视频仍可强行下载。"""
    cookie = _write_cookie(tmp_path)

    async def boom(_cred):
        raise TimeoutError("read timeout")

    monkeypatch.setattr(main.user, "get_self_info", boom)

    cred, uid = asyncio.run(main.check_cookie(cookie))
    assert cred is not None
    assert uid == 12345


def test_check_cookie_missing_file_returns_none(tmp_path):
    cred, uid = asyncio.run(main.check_cookie(str(tmp_path / "nope.json")))
    assert cred is None
    assert uid is None


def test_check_cookie_success_returns_credential(tmp_path, monkeypatch):
    cookie = _write_cookie(tmp_path)

    async def ok(_cred):
        return {"name": "测试账号"}

    monkeypatch.setattr(main.user, "get_self_info", ok)

    cred, uid = asyncio.run(main.check_cookie(cookie))
    assert cred is not None
    assert uid == 12345


# ---------- 核心运行状态信号 ----------


def _service(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "system:\n"
        f"  db_path: {tmp_path / 'archive.db'}\n"
        f"  download_path: {tmp_path / 'downloads'}\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "archive.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE assets (bvid TEXT PRIMARY KEY, title TEXT, type TEXT, "
            "status INTEGER, path TEXT, last_check TEXT, p_count INTEGER)"
        )
    return WebService(
        project_root=tmp_path,
        config_path=config_path,
        db_path=db_path,
        version="1.7.1",
    )


def test_dashboard_reports_core_not_running_without_runtime_file(tmp_path):
    """runtime.json 不存在时应明确告知核心未运行。"""
    service = _service(tmp_path)

    dashboard = service.dashboard()

    assert dashboard["core_running"] is False
    assert dashboard["runtime"] == {}


def test_dashboard_reports_core_running_with_runtime_file(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({"status": "scanning", "message": "扫描中"}), encoding="utf-8")
    service = _service(tmp_path)

    dashboard = service.dashboard()

    assert dashboard["core_running"] is True
    assert dashboard["runtime"]["status"] == "scanning"


@pytest.mark.parametrize("status", [
    "stopped",      # 守护进程正常结束或被 Ctrl+C 停止
    "complete",
    "error",
    "failed",
])
def test_dashboard_reports_core_not_running_for_terminal_states(tmp_path, status):
    """runtime.json 会留在磁盘上，但状态是终态时核心并未在运行。

    只看"文件是否存在"会把已停止的核心误报成"空闲扫描中"。
    """
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({"status": status}), encoding="utf-8")
    service = _service(tmp_path)

    dashboard = service.dashboard()

    assert dashboard["core_running"] is False
    assert dashboard["runtime"]["status"] == status


@pytest.mark.parametrize("status", ["idle", "scanning", "starting", "running"])
def test_dashboard_reports_core_running_for_active_states(tmp_path, status):
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({"status": status}), encoding="utf-8")
    service = _service(tmp_path)

    assert service.dashboard()["core_running"] is True


def test_dashboard_reports_core_not_running_after_clean_stop(tmp_path):
    """正常退出（带 stopped_at）后，即使文件仍在磁盘上也不算在运行。"""
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps({"status": "idle", "stopped_at": "2026-10-20T10:00:00+08:00"}),
        encoding="utf-8",
    )
    service = _service(tmp_path)

    assert service.dashboard()["core_running"] is False


def test_runtime_writer_stop_marks_stopped(tmp_path):
    """stop() 应写入 stopped 标记，供 WebUI 判断核心已结束。"""
    from app.core.runtime_state import RuntimeStateWriter

    path = tmp_path / "runtime.json"
    writer = RuntimeStateWriter(path)

    writer.stop("核心引擎已停止")

    import json as _json

    persisted = _json.loads(path.read_text(encoding="utf-8"))
    assert persisted["status"] == "stopped"
    assert persisted["stopped_at"]
    assert persisted["next_scan_at"] is None
    assert persisted["message"] == "核心引擎已停止"


def test_dashboard_core_running_false_on_corrupt_runtime(tmp_path):
    """runtime.json 损坏时也算核心未运行——不能因此显示成"扫描中"。"""
    path = tmp_path / "runtime.json"
    path.write_text("{not json", encoding="utf-8")
    service = _service(tmp_path)

    dashboard = service.dashboard()

    assert dashboard["core_running"] is False
