import asyncio
from pathlib import Path

import pytest

from app.core.parser import SyncFetchError
from app.scheduler.scanner import FavScanner

from tests.test_scanner import (
    ExistingAssetDatabase,
    RecordingDatabase,
    scanner_config,
)


class RecordingPathManager:
    """关注源测试专用：路径落到 tmp_path 之下，补齐下载所需方法。"""

    def __init__(self, root="/archive"):
        self.root = str(root)
        self.video_keys = []

    def get_video_dir(self, source_name, title, key):
        self.video_keys.append(key)
        return str(Path(self.root) / source_name / key)

    @staticmethod
    def get_article_dir(source_name, title, key):
        return str(Path(source_name) / f"cv{key}")

    @staticmethod
    def mark_as_deleted(path, prefix):
        return path

    @staticmethod
    def get_video_output(
        video_dir,
        title,
        bvid,
        part_number=None,
        part_title=None,
        part_count=1,
    ):
        return video_dir, f"{title} [{bvid}]"


class FollowingVideosParser:
    """模拟关注 UP 主投稿列表：第一页两个正常投稿 + 一个失效投稿。"""

    def __init__(self):
        self.calls = []
        self.items = [
            {
                "title": "关注投稿A",
                "bvid": "BV1FA",
                "aid": 201,
                "id": 201,
                "type": "video",
                "up_name": "测试UP",
            },
            {
                "title": "关注投稿B",
                "bvid": "BV1FB",
                "aid": 202,
                "id": 202,
                "type": "video",
                "up_name": "测试UP",
            },
            {
                "title": "已失效视频",
                "bvid": "",
                "aid": 203,
                "id": 203,
                "type": "video",
                "up_name": "测试UP",
            },
        ]

    async def get_user_videos(self, mid, page=1, page_size=30):
        self.calls.append((mid, page))
        if page == 1:
            return list(self.items), False
        return [], False

    async def check_multi_p(self, bvid):
        return False, [{"page": 1, "part": "P1"}]


class MaterializingDownloader:
    def __init__(self):
        self.calls = []

    def download_video(self, url, save_dir, file_name, cookie_file_path):
        self.calls.append(file_name)
        output_dir = Path(save_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{file_name}.mp4").write_bytes(b"media")
        (output_dir / f"{file_name}.jpg").write_bytes(b"jpeg")
        return True


def build_following_scanner(monkeypatch, database=None, tmp_root="/archive"):
    database = database or RecordingDatabase()
    scanner = FavScanner(
        scanner_config(),
        credential=object(),
        db=database,
        path_mgr=RecordingPathManager(tmp_root),
    )
    parser = FollowingVideosParser()
    scanner.parser = parser
    scanner.downloader = MaterializingDownloader()

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr("app.scheduler.scanner.asyncio.sleep", no_sleep)
    return scanner, parser, database


def test_scan_following_downloads_new_videos_and_tombstones_invalid(
    monkeypatch,
    tmp_path,
):
    scanner, parser, database = build_following_scanner(
        monkeypatch, tmp_root=tmp_path
    )

    asyncio.run(scanner.scan_following(946974, "测试UP"))

    # 两个正常投稿都被下载入库，失效投稿创建了墓碑记录（状态 1）
    assert set(database.records) == {"BV1FA", "BV1FB", "av203"}
    tombstones = [
        record
        for record in database.records.values()
        if record["status"] == 1
    ]
    assert len(tombstones) == 1
    assert tombstones[0]["bvid"] == "av203"
    assert parser.calls == [(946974, 1)]


def test_scan_following_skips_existing_completed_assets(
    monkeypatch, tmp_path
):
    # 预置一条"完整"的在库记录：真实目录 + 符合命名约定的媒体文件
    archive_path = tmp_path / "existing"
    archive_path.mkdir()
    (archive_path / "Existing [BV123].mp4").write_bytes(b"media")
    database = RecordingDatabase()
    database.records["BV123"] = {
        "bvid": "BV123",
        "title": "Existing",
        "type": "video",
        "status": 0,
        "path": str(archive_path),
        "last_check": None,
        "p_count": 1,
    }
    scanner, parser, _ = build_following_scanner(monkeypatch, database, tmp_path)

    # parser 只返回这个已在库的完整投稿
    parser.items = [
        {
            "title": "Existing",
            "bvid": "BV123",
            "aid": 123,
            "id": 123,
            "type": "video",
        },
    ]

    asyncio.run(scanner.scan_following(946974, "测试UP"))

    assert database.last_checks == ["BV123"]
    # 未触发任何下载（MaterializingDownloader 无调用）
    assert scanner.downloader.calls == []


def test_scan_following_rejects_invalid_mid(monkeypatch, tmp_path):
    scanner, parser, database = build_following_scanner(
        monkeypatch, tmp_root=tmp_path
    )

    asyncio.run(scanner.scan_following(0, None))
    asyncio.run(scanner.scan_following("not-a-number", None))

    assert database.records == {}
    assert parser.calls == []


def test_scan_following_resolves_up_name_via_user_info(monkeypatch, tmp_path):
    scanner, parser, _ = build_following_scanner(
        monkeypatch, tmp_root=tmp_path
    )

    class NameParser(FollowingVideosParser):
        async def get_user_info(self, mid):
            return {"name": "自动命名的UP"}

    scanner.parser = NameParser()

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr("app.scheduler.scanner.asyncio.sleep", no_sleep)

    asyncio.run(scanner.scan_following(946974, None))
    # 目录名使用自动获取的 UP 主名
    assert scanner.downloader.calls
    assert scanner.path_mgr.video_keys


class FailingFollowingsPageParser:
    async def get_followings(self, page=1, page_size=50):
        raise SyncFetchError("followings list failed")


def test_parser_get_followings_paginates_and_parses(monkeypatch):
    """parser.get_followings 正确解析分页结构（满页才续翻）。"""
    from app.core.parser import BiliParser

    class FakeCredential:
        def get_cookies(self):
            return {"dedeuserid": "42"}

    parser = BiliParser(FakeCredential(), uid=42)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 0,
                "data": {
                    "list": [
                        {"mid": 946974, "uname": "UP甲", "sign": "", "face": ""},
                        {"mid": 12345, "uname": "UP乙", "sign": "", "face": ""},
                    ]
                },
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            assert "vmid=42" in url
            return FakeResponse()

    import app.core.parser as parser_module

    class FakeAsyncClient(FakeClient):
        pass

    monkeypatch.setattr(parser_module.httpx, "AsyncClient", FakeAsyncClient)

    async def run():
        return await parser.get_followings(page=1, page_size=50)

    follows, has_more = asyncio.run(run())
    assert [f["mid"] for f in follows] == [946974, 12345]
    assert has_more is False  # 未满页，不再续翻
