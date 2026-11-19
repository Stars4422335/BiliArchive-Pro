"""QA 独立验证：P0 config_path 链路的**端到端语义**。

工程师的 `test_config_reload_chain.py` 证明的是"config_path 传到了
FavScanner"；本文件补的是产品承诺那一层：

1. 下载总开关关闭时，真实守护循环确实写出 ``phase=download_paused``，
   并且**一次下载调用都没有发生**。
2. WebUI 通过命令通道下发的 ``reload_config`` 在真实守护循环里回执成功
   （``status=done`` + "配置已热重载"），而不是"看起来 reload 了"。

这两条在 P0 缺陷（daemon_loop 漏传 config_path）存在时都会失败：
``reload_config()`` 恒为 False，命令回执变成 failed。因此它们是比单元
断言更贴近线上的反证。
"""

import asyncio
import contextlib
import json
import os

import yaml

from app.core.commands import CommandChannel, commands_path
from app.core.path_manager import PathManager
from app.core.runtime_state import runtime_state_path
from app.scheduler import daemon
from app.scheduler.scanner import FavScanner

#: 守护循环停止写入 runtime.json 之后，轮询还会空转；给足余量但保持秒级。
OBSERVE_TIMEOUT_SECONDS = 10.0


def _write_config(tmp_path, **system_overrides):
    """最小可运行配置：默认关闭下载总开关，保证测试不触网。"""
    system = {
        "download_path": str(tmp_path / "downloads"),
        "db_path": str(tmp_path / "archive.db"),
        "cookie_path": str(tmp_path / "cookie.json"),
        "plex_mode": True,
        "download_enabled": False,
        # 足够长：观测到 download_paused 后循环停在分片休眠里，不会空转刷盘。
        "scan_interval_seconds": 30,
        "max_downloads_per_run": 0,
        "check_update_on_start": False,
        "verify_integrity": "off",
    }
    system.update(system_overrides)
    config = {
        "system": system,
        "network": {},
        "components": {
            "yt-dlp": {"strategy": "auto", "path": "./bin/yt-dlp"},
            "ffmpeg": {"strategy": "auto", "path": "./bin/ffmpeg"},
        },
        "favorites": [],
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return config, config_path


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


async def _drive_until(config, config_path, runtime_path, predicate, timeout=OBSERVE_TIMEOUT_SECONDS):
    """跑真实 daemon_loop，直到 runtime.json 满足 predicate；返回该快照。"""
    task = asyncio.ensure_future(
        daemon.daemon_loop(
            config,
            cred=object(),
            uid=20241119,
            config_path=str(config_path),
        )
    )
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    observed = None
    try:
        while loop.time() < deadline:
            if task.done() and not task.cancelled():
                exc = task.exception()
                if exc is not None:  # 守护循环提前崩溃：直接把原因抛给断言
                    raise exc
            snapshot = _read_json(runtime_path)
            if snapshot is not None and predicate(snapshot):
                observed = snapshot
                break
            await asyncio.sleep(0.02)
    finally:
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
    return observed


def test_download_switch_off_pauses_the_engine_and_never_downloads(tmp_path, monkeypatch):
    """关闭下载开关 → runtime.json 出现 download_paused，且下载调用为 0。"""
    config, config_path = _write_config(tmp_path)
    runtime_path = tmp_path / "runtime.json"

    download_calls = []

    def recording_download(self, **kwargs):
        download_calls.append(kwargs)
        return True

    # 真实 Downloader 会在下载时启动 yt-dlp；这里只记录调用，绝不触网。
    monkeypatch.setattr(
        "app.core.downloader.Downloader.download_video", recording_download
    )

    observed = asyncio.run(
        _drive_until(
            config,
            config_path,
            runtime_path,
            lambda state: state.get("phase") == "download_paused",
        )
    )

    assert observed is not None, "10 秒内 runtime.json 未出现 phase=download_paused"
    assert observed["phase"] == "download_paused"
    assert observed["status"] == "idle"
    assert "下载已暂停" in observed["message"]
    # 关闭开关的意义就是"一个都不下"：下载入口必须零调用。
    assert download_calls == []
    # 暂停分支不应把轮次算成已下载，也不应残留上一次的来源。
    assert observed["downloaded_count"] == 0
    assert observed["source"] is None
    assert observed["current_asset"] is None


def test_runtime_json_lives_next_to_the_database(tmp_path):
    """pause 状态写到了 WebUI 读取的那个位置，而不是 cwd。"""
    config, _ = _write_config(tmp_path)

    assert runtime_state_path(config) == os.path.join(
        os.path.abspath(tmp_path), "runtime.json"
    )


def test_reload_config_command_is_acknowledged_ok_in_the_real_loop(tmp_path, monkeypatch):
    """WebUI 的 reload_config 在真实守护循环里回执 done（P0 的直接反证）。"""
    config, config_path = _write_config(tmp_path)
    runtime_path = tmp_path / "runtime.json"

    monkeypatch.setattr(
        "app.core.downloader.Downloader.download_video",
        lambda self, **kwargs: True,
    )

    # 模拟 WebUI 在守护进程启动前排队一条 reload_config。
    channel = CommandChannel(commands_path(config))
    queued = channel.enqueue("reload_config")
    assert queued["status"] == "pending"

    observed = asyncio.run(
        _drive_until(
            config,
            config_path,
            runtime_path,
            lambda state: state.get("phase") == "download_paused",
        )
    )
    assert observed is not None, "守护循环未进入 download_paused，无法确认命令已被消费"

    receipt = channel.command_status(queued["id"])
    assert receipt is not None
    assert receipt["status"] == "done", f"reload_config 回执失败: {receipt}"
    assert "热重载" in receipt["result"]


def test_reload_config_picks_up_the_toggled_switch(tmp_path):
    """真链路：改盘把下载开关打开后，reload_config 让 scanner 立刻看到新值。"""
    config, config_path = _write_config(tmp_path)

    scanner = FavScanner(
        config,
        credential=object(),
        db=None,
        path_mgr=PathManager(
            config["system"]["download_path"], config["system"]["plex_mode"]
        ),
        uid=20241119,
        config_path=os.path.abspath(str(config_path)),
    )
    assert scanner.download_enabled is False

    _write_config(tmp_path, download_enabled=True)

    assert scanner.reload_config() is True
    assert scanner.download_enabled is True
