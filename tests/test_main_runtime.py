import asyncio

import pytest

import main


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
    monkeypatch.setattr(main, "DatabaseManager", lambda db_path: object())
    monkeypatch.setattr(main, "PathManager", lambda root_path, plex_mode: object())
    monkeypatch.setattr(main, "FavScanner", DummyScanner)
    monkeypatch.setattr(main, "ComponentUpdater", DummyUpdater)
    monkeypatch.setattr(main.asyncio, "sleep", stop_after_first_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.daemon_loop(base_config(), cred=object(), uid=1))

    assert DummyUpdater.called is True


def test_daemon_loop_uses_configured_scan_interval(monkeypatch):
    slept = []

    async def capture_sleep(seconds):
        slept.append(seconds)
        raise asyncio.CancelledError(seconds)

    monkeypatch.setattr(main, "DatabaseManager", lambda db_path: object())
    monkeypatch.setattr(main, "PathManager", lambda root_path, plex_mode: object())
    monkeypatch.setattr(main, "FavScanner", DummyScanner)
    monkeypatch.setattr(main, "ComponentUpdater", DummyUpdater)
    monkeypatch.setattr(main.asyncio, "sleep", capture_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.daemon_loop(base_config(), cred=object(), uid=1))

    assert slept == [7]


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
