import asyncio

import pytest

import main
from app.core.parser import SyncFetchError


class DummyScanner:
    max_global_downloads = 0
    global_download_count = 0

    def __init__(self, config, cred, db, path_mgr, uid=None):
        self.parser = self

    async def get_user_favorite_lists(self):
        return []

    async def scan_favorite(self, fav_id, fav_name):
        pass

    async def scan_watch_later(self):
        pass

    async def scan_collection(self, collection_id, collection_name, mid):
        pass


class DummyDatabase:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class DummyUpdater:
    called = False

    def __init__(self, config):
        self.config = config

    async def check_all(self):
        DummyUpdater.called = True


async def stop_after_first_sleep(seconds):
    raise asyncio.CancelledError(seconds)


def base_config():
    return {
        "system": {
            "db_path": ":memory:",
            "download_path": "./downloads",
            "plex_mode": True,
            "sync_watch_later": False,
            "check_update_on_start": True,
            "scan_interval_seconds": 7,
        },
        "favorites": [{"id": 1, "name": "TestFav"}],
    }


def test_daemon_loop_runs_component_update_when_enabled(monkeypatch):
    DummyUpdater.called = False
    monkeypatch.setattr(main, "DatabaseManager", lambda db_path, **_: DummyDatabase())
    monkeypatch.setattr(main, "PathManager", lambda root_path, plex_mode: object())
    monkeypatch.setattr(main, "FavScanner", DummyScanner)
    monkeypatch.setattr(main, "ComponentUpdater", DummyUpdater)
    monkeypatch.setattr(main.asyncio, "sleep", stop_after_first_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.daemon_loop(base_config(), cred=object(), uid=1))

    assert DummyUpdater.called is True


def test_daemon_loop_applies_sdk_request_timeout(monkeypatch):
    timeouts = []
    monkeypatch.setattr(main.request_settings, "set_timeout", timeouts.append)
    monkeypatch.setattr(main, "DatabaseManager", lambda db_path, **_: DummyDatabase())
    monkeypatch.setattr(main, "PathManager", lambda root_path, plex_mode: object())
    monkeypatch.setattr(main, "FavScanner", DummyScanner)
    monkeypatch.setattr(main, "ComponentUpdater", DummyUpdater)
    monkeypatch.setattr(main.asyncio, "sleep", stop_after_first_sleep)
    config = base_config()
    config["network"] = {"request_timeout_seconds": 12}

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.daemon_loop(config, cred=object(), uid=1))

    assert timeouts == [12.0]


def test_daemon_loop_uses_configured_scan_interval(monkeypatch):
    """休眠总时长等于配置值，但被切成不超过轮询间隔的分片。

    分片是命令通道的要求：守护进程必须在休眠期间保持可唤醒，
    否则 WebUI 的 trigger_scan 要等完整休眠结束才会生效。
    """
    slept = []
    clock = {"now": 0.0}

    async def capture_sleep(seconds):
        slept.append(seconds)
        # 模拟真实时钟推进，否则分片循环的 remaining 永不递减
        clock["now"] += seconds
        if clock["now"] >= 7:
            raise asyncio.CancelledError(seconds)

    monkeypatch.setattr(main, "DatabaseManager", lambda db_path, **_: DummyDatabase())
    monkeypatch.setattr(main, "PathManager", lambda root_path, plex_mode: object())
    monkeypatch.setattr(main, "FavScanner", DummyScanner)
    monkeypatch.setattr(main, "ComponentUpdater", DummyUpdater)
    monkeypatch.setattr(main.asyncio, "sleep", capture_sleep)
    # 让 _sleep_until_next_scan 使用的时钟跟随模拟时钟推进
    monkeypatch.setattr(main, "_loop_time", lambda: clock["now"])

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.daemon_loop(base_config(), cred=object(), uid=1))

    # 总休眠时长仍等于 scan_interval_seconds
    assert sum(slept) == 7
    # 每一片都不超过轮询间隔，保证休眠期可被命令唤醒
    assert all(chunk <= main.COMMAND_POLL_INTERVAL for chunk in slept)
    assert len(slept) > 1


def test_daemon_loop_continues_after_one_source_fetch_failure(monkeypatch, capsys):
    calls = []

    class PartiallyFailingScanner(DummyScanner):
        async def scan_favorite(self, fav_id, fav_name):
            calls.append((fav_id, fav_name))
            if fav_id == 1:
                raise SyncFetchError("temporary API failure")

    config = base_config()
    config["system"]["check_update_on_start"] = False
    config["favorites"] = [
        {"id": 1, "name": "First"},
        {"id": 2, "name": "Second"},
    ]
    monkeypatch.setattr(main, "DatabaseManager", lambda db_path, **_: DummyDatabase())
    monkeypatch.setattr(main, "PathManager", lambda root_path, plex_mode: object())
    monkeypatch.setattr(main, "FavScanner", PartiallyFailingScanner)
    monkeypatch.setattr(main.asyncio, "sleep", stop_after_first_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.daemon_loop(config, cred=object(), uid=1))

    output = capsys.readouterr().out
    assert calls == [(1, "First"), (2, "Second")]
    assert "本轮扫描不完整" in output
    assert "收藏夹 First (1)" in output
    assert "本轮全量扫描完毕" not in output


def test_daemon_loop_closes_database_when_cancelled(monkeypatch):
    databases = []

    def create_database(db_path, **_):
        database = DummyDatabase()
        databases.append(database)
        return database

    monkeypatch.setattr(main, "DatabaseManager", create_database)
    monkeypatch.setattr(main, "PathManager", lambda root_path, plex_mode: object())
    monkeypatch.setattr(main, "FavScanner", DummyScanner)
    monkeypatch.setattr(main, "ComponentUpdater", DummyUpdater)
    monkeypatch.setattr(main.asyncio, "sleep", stop_after_first_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.daemon_loop(base_config(), cred=object(), uid=1))

    assert len(databases) == 1
    assert databases[0].closed is True


def test_daemon_loop_passes_collection_owner_mid(monkeypatch):
    calls = []

    class RecordingCollectionScanner(DummyScanner):
        async def scan_collection(self, collection_id, collection_name, mid):
            calls.append((collection_id, collection_name, mid))

    config = base_config()
    config["system"]["check_update_on_start"] = False
    config["sync_collections"] = [
        {"id": 88, "mid": 77, "name": "Test collection"}
    ]
    monkeypatch.setattr(main, "DatabaseManager", lambda db_path, **_: DummyDatabase())
    monkeypatch.setattr(main, "PathManager", lambda root_path, plex_mode: object())
    monkeypatch.setattr(main, "FavScanner", RecordingCollectionScanner)
    monkeypatch.setattr(main.asyncio, "sleep", stop_after_first_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.daemon_loop(config, cred=object(), uid=1))

    assert calls == [(88, "Test collection", 77)]


def test_daemon_loop_marks_collection_without_mid_incomplete(monkeypatch, capsys):
    config = base_config()
    config["system"]["check_update_on_start"] = False
    config["sync_collections"] = [{"id": 88, "name": "Missing owner"}]
    monkeypatch.setattr(main, "DatabaseManager", lambda db_path, **_: DummyDatabase())
    monkeypatch.setattr(main, "PathManager", lambda root_path, plex_mode: object())
    monkeypatch.setattr(main, "FavScanner", DummyScanner)
    monkeypatch.setattr(main.asyncio, "sleep", stop_after_first_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.daemon_loop(config, cred=object(), uid=1))

    output = capsys.readouterr().out
    assert "缺少有效的 id 或 mid" in output
    assert "本轮扫描不完整" in output


def test_load_config_merges_local_overrides(monkeypatch, tmp_path):
    (tmp_path / "config.yaml").write_text(
        """
system:
  sync_watch_later: false
  scan_interval_seconds: 21600
favorites: []
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "config.local.yaml").write_text(
        """
system:
  sync_watch_later: true
favorites:
  - id: 9999999999
    name: TestFav
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = main.load_config()

    assert config["system"]["sync_watch_later"] is True
    assert config["system"]["scan_interval_seconds"] == 21600
    assert config["favorites"] == [{"id": 9999999999, "name": "TestFav"}]


def test_load_config_rejects_non_mapping_local_config(monkeypatch, tmp_path):
    (tmp_path / "config.yaml").write_text("system: {}\n", encoding="utf-8")
    (tmp_path / "config.local.yaml").write_text("- invalid\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="顶层必须是映射结构"):
        main.load_config()
