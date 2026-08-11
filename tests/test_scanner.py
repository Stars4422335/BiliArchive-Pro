import asyncio
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from bilibili_api import aid2bvid

from app.core.parser import SyncFetchError
from app.core.path_manager import PathManager
from app.scheduler.scanner import FavScanner


class ExistingAssetDatabase:
    def __init__(self, archive_path="/archive/existing"):
        self.last_checks = []
        self.archive_path = archive_path

    def get_asset(self, key):
        return {
            "bvid": key,
            "title": "Existing",
            "type": "video",
            "status": 0,
            "path": self.archive_path,
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
        self.last_checks = []

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

    def update_last_check(self, key):
        self.last_checks.append(key)


class RecordingPathManager:
    def __init__(self):
        self.video_keys = []

    def get_video_dir(self, source_name, title, key):
        self.video_keys.append(key)
        return f"/archive/{source_name}/{key}"

    @staticmethod
    def get_article_dir(source_name, title, key):
        return f"/archive/{source_name}/cv{key}"

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


class MediaOutputParser:
    def __init__(self, pages):
        self.pages = pages
        self.item = {
            "title": "测试多P",
            "bvid": "BV123",
            "aid": 123,
            "id": 123,
            "type": "video",
            "up_name": "测试UP",
            "intro": "简介",
            "pubtime": 1704067200,
        }

    async def get_favorite_list(self, fav_id, page):
        return ([dict(self.item)], False) if page == 1 else ([], False)

    async def check_multi_p(self, bvid):
        return len(self.pages) > 1, list(self.pages)


class MaterializingDownloader:
    def __init__(self, fail_on_call=None):
        self.calls = []
        self.fail_on_call = fail_on_call

    def download_video(self, url, save_dir, file_name, cookie_file_path):
        self.calls.append(
            {
                "url": url,
                "save_dir": save_dir,
                "file_name": file_name,
                "cookie_file_path": cookie_file_path,
            }
        )
        if len(self.calls) == self.fail_on_call:
            return False

        output_dir = Path(save_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{file_name}.mp4").write_bytes(b"media")
        (output_dir / f"{file_name}.jpg").write_bytes(b"jpeg")
        return True


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


def test_scanner_propagates_second_page_fetch_failure(monkeypatch, tmp_path):
    archive_path = tmp_path / "existing"
    archive_path.mkdir()
    (archive_path / "Existing [BV123].mp4").write_bytes(b"media")
    database = ExistingAssetDatabase(str(archive_path))
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
        lambda *args, **kwargs: "/archive/tombstone.nfo",
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
        lambda *args, **kwargs: "/archive/tombstone.nfo",
    )

    asyncio.run(scanner.scan_favorite(99, "Test favorite"))

    assert set(database.records) == {existing_bvid}
    assert database.records[existing_bvid]["status"] == 2
    assert database.writes == [existing_bvid]
    assert path_manager.video_keys == []


def build_media_output_scanner(tmp_path, plex_mode, pages, fail_on_call=None):
    database = RecordingDatabase()
    path_manager = PathManager(str(tmp_path), plex_mode=plex_mode)
    scanner = FavScanner(
        scanner_config(),
        credential=object(),
        db=database,
        path_mgr=path_manager,
    )
    scanner.parser = MediaOutputParser(pages)
    scanner.downloader = MaterializingDownloader(fail_on_call=fail_on_call)
    return scanner, database, path_manager


def test_plex_multi_part_download_creates_season_layout_and_matching_metadata(tmp_path):
    scanner, database, path_manager = build_media_output_scanner(
        tmp_path,
        plex_mode=True,
        pages=[
            {"page": 1, "part": "第一/集"},
            {"page": 2, "part": "第二集"},
        ],
    )

    asyncio.run(scanner.scan_favorite(99, "测试收藏夹"))

    calls = scanner.downloader.calls
    assert [call["url"] for call in calls] == [
        "https://www.bilibili.com/video/BV123?p=1",
        "https://www.bilibili.com/video/BV123?p=2",
    ]
    assert all(os.path.basename(call["save_dir"]) == "Season 01" for call in calls)
    assert calls[0]["file_name"].startswith("S01E01 - 第一_集")
    assert calls[1]["file_name"].startswith("S01E02 - 第二集")
    assert calls[0]["file_name"] != calls[1]["file_name"]

    record = database.records["BV123"]
    assert record["p_count"] == 2
    video_dir = Path(record["path"])
    assert video_dir == Path(
        path_manager.get_video_dir("测试收藏夹", "测试多P", "BV123")
    )
    assert (video_dir / "tvshow.nfo").exists()
    assert (video_dir / "poster.jpg").read_bytes() == b"jpeg"

    for index, call in enumerate(calls, start=1):
        media_dir = Path(call["save_dir"])
        stem = call["file_name"]
        episode = ET.parse(media_dir / f"{stem}.nfo").getroot()
        assert episode.tag == "episodedetails"
        assert episode.findtext("episode") == str(index)
        assert (media_dir / f"{stem}-thumb.jpg").exists()


def test_flat_multi_part_download_uses_unique_p_names_without_tvshow(tmp_path):
    scanner, database, _ = build_media_output_scanner(
        tmp_path,
        plex_mode=False,
        pages=[
            {"page": 1, "part": "第一集"},
            {"page": 2, "part": "第二集"},
        ],
    )

    asyncio.run(scanner.scan_favorite(99, "测试收藏夹"))

    calls = scanner.downloader.calls
    assert len({call["file_name"] for call in calls}) == 2
    assert calls[0]["file_name"].startswith("P01 - 第一集")
    assert calls[1]["file_name"].startswith("P02 - 第二集")
    assert len({call["save_dir"] for call in calls}) == 1
    video_dir = Path(database.records["BV123"]["path"])
    assert not (video_dir / "tvshow.nfo").exists()
    for call in calls:
        nfo = ET.parse(video_dir / f"{call['file_name']}.nfo").getroot()
        assert nfo.tag == "movie"


def test_multi_part_failure_does_not_mark_database_complete(tmp_path):
    scanner, database, _ = build_media_output_scanner(
        tmp_path,
        plex_mode=True,
        pages=[
            {"page": 1, "part": "第一集"},
            {"page": 2, "part": "第二集"},
        ],
        fail_on_call=2,
    )

    asyncio.run(scanner.scan_favorite(99, "测试收藏夹"))

    assert len(scanner.downloader.calls) == 2
    assert database.records == {}
    assert database.writes == []
    assert scanner.global_download_count == 0


def test_single_part_download_keeps_movie_layout_and_matching_nfo(tmp_path):
    scanner, database, _ = build_media_output_scanner(
        tmp_path,
        plex_mode=True,
        pages=[{"page": 1, "part": "单集"}],
    )

    asyncio.run(scanner.scan_favorite(99, "测试收藏夹"))

    assert len(scanner.downloader.calls) == 1
    call = scanner.downloader.calls[0]
    assert "?p=" not in call["url"]
    video_dir = Path(database.records["BV123"]["path"])
    assert Path(call["save_dir"]) == video_dir
    assert (video_dir / f"{call['file_name']}.nfo").exists()
    assert (video_dir / "poster.jpg").exists()


def test_incomplete_multi_part_record_is_redownloaded(tmp_path):
    scanner, database, path_manager = build_media_output_scanner(
        tmp_path,
        plex_mode=True,
        pages=[
            {"page": 1, "part": "第一集"},
            {"page": 2, "part": "第二集"},
        ],
    )
    video_dir = Path(
        path_manager.get_video_dir("测试收藏夹", "测试多P", "BV123")
    )
    season_dir = video_dir / "Season 01"
    season_dir.mkdir(parents=True)
    (season_dir / "S01E01 - 第一集 [BV123-P1].mp4").write_bytes(b"media")
    (season_dir / "old-unrelated.mp4").write_bytes(b"old media")
    database.records["BV123"] = {
        "bvid": "BV123",
        "title": "测试多P",
        "type": "video",
        "status": 0,
        "path": str(video_dir),
        "last_check": None,
        "p_count": 2,
    }

    asyncio.run(scanner.scan_favorite(99, "测试收藏夹"))

    assert len(scanner.downloader.calls) == 2
    assert database.records["BV123"]["p_count"] == 2
    assert database.writes == ["BV123"]
    assert database.last_checks == []


def test_complete_multi_part_record_is_skipped_and_last_check_updated(tmp_path):
    scanner, database, path_manager = build_media_output_scanner(
        tmp_path,
        plex_mode=True,
        pages=[
            {"page": 1, "part": "第一集"},
            {"page": 2, "part": "第二集"},
        ],
    )
    video_dir = Path(
        path_manager.get_video_dir("测试收藏夹", "测试多P", "BV123")
    )
    season_dir = video_dir / "Season 01"
    season_dir.mkdir(parents=True)
    for index, part_title in enumerate(("第一集", "第二集"), start=1):
        media_dir, file_name = path_manager.get_video_output(
            str(video_dir),
            "测试多P",
            "BV123",
            part_number=index,
            part_title=part_title,
            part_count=2,
        )
        media_path = Path(media_dir) / f"{file_name}.mp4"
        media_path.write_bytes(f"media-{index}".encode("ascii"))
    database.records["BV123"] = {
        "bvid": "BV123",
        "title": "测试多P",
        "type": "video",
        "status": 0,
        "path": str(video_dir),
        "last_check": None,
        "p_count": 2,
    }

    asyncio.run(scanner.scan_favorite(99, "测试收藏夹"))

    assert scanner.downloader.calls == []
    assert database.writes == []
    assert database.last_checks == ["BV123"]


@pytest.mark.parametrize(
    "pages",
    [
        [{"page": 1, "part": "单集"}],
        [
            {"page": 1, "part": "第一集"},
            {"page": 2, "part": "第二集"},
        ],
    ],
)
def test_artwork_failure_does_not_mark_database_complete(
    monkeypatch,
    tmp_path,
    pages,
):
    scanner, database, _ = build_media_output_scanner(
        tmp_path,
        plex_mode=True,
        pages=pages,
    )
    monkeypatch.setattr(
        "app.scheduler.scanner.MetadataGenerator.copy_artwork",
        lambda *args, **kwargs: None,
    )

    asyncio.run(scanner.scan_favorite(99, "测试收藏夹"))

    assert database.records == {}
    assert database.writes == []
    assert scanner.global_download_count == 0


@pytest.mark.parametrize("source", ["favorite", "watch_later", "collection"])
def test_tombstone_nfo_failure_does_not_mark_database_complete(
    monkeypatch,
    source,
):
    database = RecordingDatabase()
    scanner = FavScanner(
        scanner_config(),
        credential=object(),
        db=database,
        path_mgr=RecordingPathManager(),
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

    assert database.records == {}
    assert database.writes == []


def test_article_nfo_failure_does_not_mark_database_complete(monkeypatch):
    class ArticleParser:
        async def get_favorite_list(self, fav_id, page):
            return (
                [
                    {
                        "id": 123,
                        "title": "测试专栏",
                        "type": "article",
                        "up_name": "测试UP",
                    }
                ],
                False,
            )

    database = RecordingDatabase()
    scanner = FavScanner(
        scanner_config(),
        credential=object(),
        db=database,
        path_mgr=RecordingPathManager(),
    )
    scanner.parser = ArticleParser()
    monkeypatch.setattr(
        "app.scheduler.scanner.MetadataGenerator.process_article_to_md",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.scheduler.scanner.MetadataGenerator.create_nfo",
        lambda *args, **kwargs: None,
    )

    asyncio.run(scanner.scan_favorite(99, "Test favorite"))

    assert database.records == {}
    assert database.writes == []
    assert scanner.global_download_count == 0
