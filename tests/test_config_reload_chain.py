"""config_path 传递链路回归：从 daemon_loop 到 FavScanner.reload_config。

历史缺陷：`main.py` 以 `config_path="config.yaml"` 调用 `daemon_loop`，但
`daemon_loop` 调 `_run_scan_loop` 时漏传该参数，于是 `FavScanner.config_path`
恒为 None，`reload_config()` 第一行就 `return False`。WebUI 保存设置后下发的
`reload_config` 命令永远回执失败，下载总开关、扫描间隔、来源列表全部热更失效。

这些用例刻意**不** mock 扫描器：monkeypatch 成真实 `FavScanner` 的子类，
让真实的配置读取、字段刷新逻辑跑一遍，避免"测试通过但线上仍断链"。
"""

import asyncio
import os

import pytest
import yaml

from app.scheduler import daemon
from app.scheduler.scanner import FavScanner

#: 守护循环在等待登录 / 分片休眠时都会走到 asyncio.sleep，2 秒足够跑完
#: 一整轮"构造扫描器 → 下载暂停 → 分片休眠"，同时不会拖慢测试套件。
DAEMON_TIMEOUT_SECONDS = 2.0


def _write_config(config_path, **system_overrides):
    """写一份最小可运行配置；默认关闭下载，保证测试不触网。"""
    system = {
        "download_path": "./downloads",
        "db_path": str(config_path.parent / "archive.db"),
        "cookie_path": str(config_path.parent / "cookie.json"),
        "plex_mode": True,
        # 关闭下载总开关：守护循环走 download_paused 分支，
        # 不解析收藏夹、不调用任何 B 站接口。
        "download_enabled": False,
        "scan_interval_seconds": 0.1,
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
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True),
        encoding="utf-8",
    )
    return config


def _run_daemon_round(monkeypatch, config, config_file, config_path_argument):
    """跑一轮真实守护循环并返回观测结果。

    monkeypatch 的是 `app.scheduler.daemon.FavScanner`（daemon 里的引用），
    子类继承真实实现，只在 `__init__` 里把自己登记下来。
    """
    captured = []

    class CapturingScanner(FavScanner):
        def __init__(self, *args, **kwargs):
            captured.append(self)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("app.scheduler.daemon.FavScanner", CapturingScanner)

    observed = {}

    async def drive():
        task = asyncio.ensure_future(
            daemon.daemon_loop(
                config,
                cred=object(),
                uid=12345,
                config_path=config_path_argument,
            )
        )
        try:
            # 等守护循环真正构造出扫描器（构造发生在第一次 await 之前）。
            for _ in range(100):
                if captured:
                    break
                await asyncio.sleep(0.02)
            if not captured:
                return
            scanner = captured[0]
            observed["scanner"] = scanner
            observed["config_path"] = scanner.config_path
            observed["first_reload"] = scanner.reload_config()
            observed["before_interval"] = scanner.config["system"]["scan_interval_seconds"]
            # 模拟 WebUI 保存设置：改写磁盘配置，再看扫描器能否读到新值。
            _write_config(
                config_file,
                scan_interval_seconds=0.3,
                max_downloads_per_run=7,
            )
            observed["second_reload"] = scanner.reload_config()
            observed["after_interval"] = scanner.config["system"]["scan_interval_seconds"]
            observed["after_max_downloads"] = scanner.config["system"]["max_downloads_per_run"]
            observed["download_enabled"] = scanner.download_enabled
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    try:
        asyncio.run(asyncio.wait_for(drive(), timeout=DAEMON_TIMEOUT_SECONDS))
    except (asyncio.TimeoutError, asyncio.CancelledError):
        # 超时只用于终止守护循环；断言在下方统一执行，避免掩盖真实结论。
        pass
    return observed


def test_daemon_passes_config_path_and_reload_reaches_disk(monkeypatch, tmp_path):
    """真实链路：daemon_loop 透传 config_path，reload_config 能读到磁盘新值。"""
    config_path = tmp_path / "config.yaml"
    config = _write_config(config_path)

    observed = _run_daemon_round(monkeypatch, config, config_path, str(config_path))

    assert "scanner" in observed, "守护循环未构造出扫描器，链路提前中断"
    scanner = observed["scanner"]
    # 关键断言：config_path 一路传到了扫描器，而不是留在 daemon_loop 里。
    assert observed["config_path"] == os.path.abspath(str(config_path))
    assert observed["first_reload"] is True
    assert observed["before_interval"] == 0.1
    # 改盘后能读到新值，说明 reload_config 不是"假成功"。
    assert observed["second_reload"] is True
    assert observed["after_interval"] == 0.3
    assert observed["after_max_downloads"] == 7
    # 下载开关在两次重载中都保持关闭（测试不触网的前提）。
    assert observed["download_enabled"] is False
    assert scanner.config["system"]["download_enabled"] is False


def test_relative_config_path_is_normalized_to_absolute(monkeypatch, tmp_path):
    """进程 chdir 后相对路径会失效，入口必须规范成绝对路径。"""
    config_path = tmp_path / "config.yaml"
    config = _write_config(config_path)
    monkeypatch.chdir(tmp_path)

    observed = _run_daemon_round(monkeypatch, config, config_path, "config.yaml")

    assert "scanner" in observed, "守护循环未构造出扫描器，链路提前中断"
    assert observed["config_path"] == os.path.abspath("config.yaml")
    assert os.path.isabs(observed["config_path"])
    assert observed["first_reload"] is True


def test_missing_config_path_keeps_reload_fail_closed(monkeypatch, tmp_path):
    """无配置路径时明确失败（None 不参与 abspath，避免变成当前目录）。"""
    config_path = tmp_path / "config.yaml"
    config = _write_config(config_path)

    observed = _run_daemon_round(monkeypatch, config, config_path, None)

    assert "scanner" in observed, "守护循环未构造出扫描器，链路提前中断"
    assert observed["config_path"] is None
    assert observed["first_reload"] is False


@pytest.mark.parametrize("empty_value", ["", None])
def test_empty_config_path_stays_none(monkeypatch, tmp_path, empty_value):
    """空串与 None 一视同仁：abspath("") 会变成 cwd，必须拦住。"""
    config_path = tmp_path / "config.yaml"
    config = _write_config(config_path)

    observed = _run_daemon_round(monkeypatch, config, config_path, empty_value)

    assert observed["config_path"] is None
