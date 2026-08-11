import asyncio

import pytest

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
