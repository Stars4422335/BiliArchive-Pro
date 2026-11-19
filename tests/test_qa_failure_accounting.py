"""QA 独立验证：一次失败事件只应该让退避账本 +1。

历史缺陷（已修复）：`_download_video_item` 的资产级兜底会登记一次失败账本，
而 `favorites.py` 在 `download_result` 为假时又登记一次。两条路径叠加后，
**一次异常事件**会让 `fail_count` 从 1 直接跳到 2（冷却从 1 小时抬到 6 小时），
与"第 1 次失败冷却 1 小时"的策略契约不符。

修复方式：`_download_video_item` 只负责"隔离异常 + 上报进度 + 返回 None"，
退避登记统一由调用方的失败分支完成。本例已从 xfail 改为正式断言。
"""

import asyncio

from app.core.path_manager import PathManager
from app.scheduler.scanner import FavScanner
from app.scheduler.sources.base import ScannerBase


class LedgerCountingDatabase:
    def __init__(self):
        self.failure_calls = []

    def get_asset(self, key):
        return None

    def update_asset(self, *args, **kwargs):
        return None

    def update_last_check(self, key):
        return None

    def record_download_failure(self, key, reason=""):
        self.failure_calls.append((key, reason))
        return len(self.failure_calls)

    def reset_download_failures(self, key):
        return True


class SingleItemParser:
    async def get_favorite_list(self, fav_id, page):
        if page != 1:
            return [], False
        return ([{"title": "会炸的视频", "bvid": "BV1boom", "aid": 1, "id": 1, "type": "video"}], False)

    async def check_multi_p(self, bvid):
        return False, [{"page": 1, "part": "单集"}]


class ExplodingDownloader:
    def download_video(self, **kwargs):
        raise RuntimeError("磁盘满")


def build_scanner(tmp_path, database, monkeypatch):
    config = {
        "system": {
            "cookie_path": "cookie.json",
            "min_disk_gb": 0,
            "max_downloads_per_run": 0,
            "plex_mode": True,
        },
        "network": {
            "sync_retry_attempts": 1,
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
    scanner = FavScanner(
        config,
        credential=object(),
        db=database,
        path_mgr=PathManager(str(tmp_path), plex_mode=True),
    )
    scanner.parser = SingleItemParser()
    scanner.downloader = ExplodingDownloader()
    monkeypatch.setattr(ScannerBase, "_login_gate_open", lambda self: True)
    monkeypatch.setattr(
        "app.scheduler.sources.download.MetadataGenerator.copy_artwork",
        lambda *args, **kwargs: "/archive/poster.jpg",
    )
    monkeypatch.setattr(
        "app.scheduler.sources.download.MetadataGenerator.create_nfo",
        lambda *args, **kwargs: "/archive/video.nfo",
    )
    return scanner


def test_one_exception_registers_exactly_one_failure(monkeypatch, tmp_path):
    """一次异常事件只登记一次失败（冷却 1 小时，而不是被抬到 6 小时）。"""
    database = LedgerCountingDatabase()
    scanner = build_scanner(tmp_path, database, monkeypatch)

    asyncio.run(scanner.scan_favorite(1, "测试收藏夹"))

    assert len(database.failure_calls) == 1, (
        f"一次失败事件登记了 {len(database.failure_calls)} 次: {database.failure_calls}"
    )
    # 账本键就是资产的 bvid，理由里带得出这是哪一类失败
    key, reason = database.failure_calls[0]
    assert key == "BV1boom"
    assert reason


def test_unexpected_exception_is_isolated_per_asset(monkeypatch, tmp_path):
    """同一来源里的异常只报废该资产：扫描不中断，也不会登记两次。"""
    database = LedgerCountingDatabase()
    scanner = build_scanner(tmp_path, database, monkeypatch)

    # 不应抛异常（修复前 RuntimeError 会穿出 scan_favorite）
    asyncio.run(scanner.scan_favorite(1, "测试收藏夹"))

    assert scanner.global_download_count == 0
    assert len(database.failure_calls) == 1
