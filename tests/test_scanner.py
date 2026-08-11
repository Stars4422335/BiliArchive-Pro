import asyncio

import pytest
from bilibili_api import aid2bvid

from app.core.parser import SyncFetchError
from app.scheduler.scanner import FavScanner


class ExistingAssetDatabase:
    def __init__(self):
        self.last_checks = []

    def get_asset(self, key):
        return {
            "bvid": key,
            "title": "Existing",
            "type": "video",
            "status": 0,
            "path": "/archive/existing",
            "last_check": None,
            "p_count": 1,
        }

    def update_last_check(self, key):
        self.last_checks.append(key)


class FailingSecondPageParser:
    async def get_favorite_list(self, fav_id, page):
        if page == 1:
            return (
                [
                    {
                        "title": "Existing",
                        "bvid": "BV123",
                        "id": 123,
                        "type": "video",
                    }
                ],
                True,
            )
        raise SyncFetchError("page 2 failed")


class EmptyFirstPageParser:
    def __init__(self):
        self.pages = []

    async def get_favorite_list(self, fav_id, page):
        self.pages.append(page)
        if page == 1:
            return [], True
        return [], False


class UnusedPathManager:
    pass


class RecordingDatabase:
    def __init__(self):
        self.records = {}
        self.writes = []

    def get_asset(self, key):
        return self.records.get(key)

    def update_asset(self, key, title, asset_type, status, path, p_count=1):
        record = {
            "bvid": key,
            "title": title,
            "type": asset_type,
            "status": status,
            "path": path,
            "last_check": None,
            "p_count": p_count,
        }
        self.records[key] = record
        self.writes.append(key)


class RecordingPathManager:
    def __init__(self):
        self.video_keys = []

    def get_video_dir(self, source_name, title, key):
        self.video_keys.append(key)
        return f"/archive/{source_name}/{key}"

    @staticmethod
    def mark_as_deleted(path, prefix):
        return path


class InvalidVideoParser:
    def __init__(self):
        self.items = [
            {
                "title": "已失效视频",
                "bvid": "",
                "aid": 101,
                "id": 101,
                "type": "video",
            },
            {
                "title": "已失效视频",
                "bvid": None,
                "aid": 102,
                "id": 102,
                "type": "video",
            },
        ]

    async def get_favorite_list(self, fav_id, page):
        return list(self.items), False

    async def get_watch_later_list(self):
        return list(self.items)

    async def get_collection_list(self, collection_id, page, mid=None):
        return list(self.items), False


def scanner_config():
    return {
        "system": {
            "cookie_path": "cookie.json",
            "min_disk_gb": 0,
            "max_downloads_per_run": 0,
        },
        "network": {
            "sync_retry_attempts": 2,
            "sync_retry_backoff_seconds": 0,
            "request_timeout_seconds": 10,
        },
        "components": {
            "yt-dlp": {"path": "yt-dlp"},
            "ffmpeg": {"path": "ffmpeg"},
        },
        "archive_protection": {
            "tombstone_prefix": "[Tombstone]",
            "mark_deleted_prefix": "[Deleted]",
        },
    }


def test_scanner_propagates_second_page_fetch_failure(monkeypatch):
    database = ExistingAssetDatabase()
    scanner = FavScanner(
        scanner_config(),
        credential=object(),
        db=database,
        path_mgr=UnusedPathManager(),
    )
    scanner.parser = FailingSecondPageParser()

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr("app.scheduler.scanner.asyncio.sleep", no_sleep)

    with pytest.raises(SyncFetchError, match="page 2 failed"):
        asyncio.run(scanner.scan_favorite(99, "Test favorite"))

    assert database.last_checks == ["BV123"]


def test_scanner_continues_after_empty_page_when_more_pages_exist(monkeypatch):
    database = ExistingAssetDatabase()
    scanner = FavScanner(
        scanner_config(),
        credential=object(),
        db=database,
        path_mgr=UnusedPathManager(),
    )
    parser = EmptyFirstPageParser()
    scanner.parser = parser

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr("app.scheduler.scanner.asyncio.sleep", no_sleep)

    asyncio.run(scanner.scan_favorite(99, "Test favorite"))

    assert parser.pages == [1, 2]


@pytest.mark.parametrize("source", ["favorite", "watch_later", "collection"])
def test_invalid_videos_use_stable_unique_keys_across_scans(monkeypatch, source):
    database = RecordingDatabase()
    path_manager = RecordingPathManager()
    scanner = FavScanner(
        scanner_config(),
        credential=object(),
        db=database,
        path_mgr=path_manager,
    )
    scanner.parser = InvalidVideoParser()
    monkeypatch.setattr(
        "app.scheduler.scanner.MetadataGenerator.create_nfo",
        lambda *args, **kwargs: None,
    )

    if source == "favorite":
        operation = lambda: scanner.scan_favorite(99, "Test favorite")
    elif source == "watch_later":
        operation = scanner.scan_watch_later
    else:
        operation = lambda: scanner.scan_collection(88, "Test collection", 77)

    asyncio.run(operation())
    asyncio.run(operation())

    assert set(database.records) == {"av101", "av102"}
    assert database.writes == ["av101", "av102"]
    assert path_manager.video_keys == ["av101", "av102"]
    assert "unknown" not in path_manager.video_keys


def test_video_asset_key_rejects_unidentifiable_invalid_video():
    assert FavScanner._video_asset_key({"bvid": "BV123", "aid": 101}) == "BV123"
    assert FavScanner._video_asset_key({"bvid": "", "aid": "00101"}) == "av101"
    assert FavScanner._video_asset_key({"bvid": None, "aid": 0, "id": None}) is None


def test_invalid_video_matches_existing_bvid_record_by_aid(monkeypatch):
    database = RecordingDatabase()
    existing_bvid = aid2bvid(101)
    database.records[existing_bvid] = {
        "bvid": existing_bvid,
        "title": "Archived video",
        "type": "video",
        "status": 0,
        "path": "/archive/existing",
        "last_check": None,
        "p_count": 1,
    }
    path_manager = RecordingPathManager()
    scanner = FavScanner(
        scanner_config(),
        credential=object(),
        db=database,
        path_mgr=path_manager,
    )
    parser = InvalidVideoParser()
    parser.items = [parser.items[0]]
    scanner.parser = parser
    monkeypatch.setattr(
        "app.scheduler.scanner.MetadataGenerator.create_nfo",
        lambda *args, **kwargs: None,
    )

    asyncio.run(scanner.scan_favorite(99, "Test favorite"))

    assert set(database.records) == {existing_bvid}
    assert database.records[existing_bvid]["status"] == 2
    assert database.writes == [existing_bvid]
    assert path_manager.video_keys == []
