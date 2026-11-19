"""下载失败退避账本：纯函数阶梯 + 数据库列迁移 + 扫描端接入。"""

import asyncio
import sqlite3
from datetime import datetime, timedelta

import pytest

from app.core.database_manager import DatabaseManager
from app.core.path_manager import PathManager
from app.core.retry_policy import (
    backoff_seconds,
    failure_count,
    format_duration,
    parse_last_fail,
    remaining_backoff_seconds,
    should_skip_for_backoff,
)
from app.scheduler.scanner import FavScanner
from app.scheduler.sources.base import ScannerBase

HOUR = 3600
DAY = 86400


# ---------- 阶梯边界 ----------


@pytest.mark.parametrize(
    "count,expected",
    [
        (0, 0),
        (-1, 0),
        (1, HOUR),
        (2, 6 * HOUR),
        (3, DAY),
        (4, 7 * DAY),
        # 超过阶梯长度后固定在最后一档，退避不无限增长
        (5, 7 * DAY),
        (99, 7 * DAY),
    ],
)
def test_backoff_ladder_boundaries(count, expected):
    assert backoff_seconds(count) == expected


@pytest.mark.parametrize("invalid", [None, True, False, "abc", "", [], {}, float("nan")])
def test_backoff_treats_invalid_count_as_never_failed(invalid):
    assert backoff_seconds(invalid) == 0
    assert failure_count({"fail_count": invalid}) == 0


def test_backoff_respects_custom_base_and_cap():
    assert backoff_seconds(1, base=60) == 60
    assert backoff_seconds(2, base=60) == 360
    assert backoff_seconds(3, base=60) == 24 * 60
    # cap 小于阶梯值时按 cap 封顶
    assert backoff_seconds(3, base=60, cap=1000) == 1000
    assert backoff_seconds(4, base=60, cap=1000) == 1000


@pytest.mark.parametrize("bad_base", [0, -1, "x", None, float("inf")])
def test_backoff_falls_back_to_defaults_on_invalid_base(bad_base):
    assert backoff_seconds(1, base=bad_base) == HOUR


# ---------- last_fail 解析与冷却判定 ----------


def test_parse_last_fail_accepts_iso_and_rejects_garbage():
    assert parse_last_fail("2024-01-02 03:04:05") == datetime(2024, 1, 2, 3, 4, 5)
    assert parse_last_fail("2024-01-02T03:04:05") == datetime(2024, 1, 2, 3, 4, 5)
    assert parse_last_fail("") is None
    assert parse_last_fail(None) is None
    assert parse_last_fail("昨天") is None
    assert parse_last_fail(12345) is None


def test_never_failed_asset_is_never_skipped():
    assert should_skip_for_backoff(None) is False
    assert should_skip_for_backoff({}) is False
    assert should_skip_for_backoff({"fail_count": 0, "last_fail": "2024-01-02 03:04:05"}) is False


def test_missing_or_invalid_last_fail_does_not_freeze_asset():
    """账本时间戳不可用时宁可再试一次，也不要把资产永久冻在跳过分支。"""
    assert should_skip_for_backoff({"fail_count": 3}) is False
    assert should_skip_for_backoff({"fail_count": 3, "last_fail": None}) is False
    assert should_skip_for_backoff({"fail_count": 3, "last_fail": "not-a-timestamp"}) is False


def test_recent_failure_is_in_cooldown():
    now = datetime(2024, 5, 1, 12, 0, 0)
    record = {"fail_count": 1, "last_fail": "2024-05-01 11:30:00"}

    assert should_skip_for_backoff(record, now) is True
    assert remaining_backoff_seconds(record, now) == 30 * 60


def test_clock_advances_past_the_ladder_and_unfreezes():
    now = datetime(2024, 5, 1, 12, 0, 0)
    record = {"fail_count": 2, "last_fail": "2024-05-01 11:00:00"}
    # 第 2 次失败冷却 6 小时：1 小时后仍在冷却
    assert should_skip_for_backoff(record, now) is True
    # 时钟前进到冷却结束之后立刻放行
    later = now + timedelta(hours=5, seconds=1)
    assert should_skip_for_backoff(record, later) is False
    assert remaining_backoff_seconds(record, later) == 0


def test_second_failure_escalates_the_cooldown():
    now = datetime(2024, 5, 1, 12, 0, 0)
    first = {"fail_count": 1, "last_fail": "2024-05-01 11:00:00"}
    second = {"fail_count": 2, "last_fail": "2024-05-01 11:00:00"}

    assert should_skip_for_backoff(first, now) is False  # 1 小时档已过期
    assert should_skip_for_backoff(second, now) is True  # 6 小时档仍在冷却


def test_timezone_aware_last_fail_works_with_both_clock_kinds():
    aware = datetime(2024, 5, 1, 12, 0, 0).astimezone()
    record = {"fail_count": 1, "last_fail": aware.isoformat()}

    assert should_skip_for_backoff(record, aware + timedelta(minutes=1)) is True
    assert should_skip_for_backoff(record, aware + timedelta(hours=2)) is False
    # 传入 naive 时钟也不应因 aware/naive 相减报错
    assert should_skip_for_backoff(record, aware.replace(tzinfo=None)) is True


def test_future_last_fail_is_treated_as_just_failed():
    """系统时钟回拨时不能出现负剩余时长，否则冷却会被直接绕过。"""
    now = datetime(2024, 5, 1, 12, 0, 0)
    record = {"fail_count": 1, "last_fail": "2024-05-01 18:00:00"}

    assert should_skip_for_backoff(record, now) is True
    assert remaining_backoff_seconds(record, now) == HOUR


def test_format_duration_reads_naturally():
    assert format_duration(0) == "0 秒"
    assert format_duration(90) == "1 分钟"
    assert format_duration(3600) == "1 小时 0 分钟"
    assert format_duration(7 * DAY) == "7 天 0 小时"
    assert format_duration("bad") == "0 秒"


# ---------- 数据库：迁移与账本 ----------


def test_new_database_exposes_zero_failure_columns(tmp_path):
    manager = DatabaseManager(tmp_path / "archive.db")
    manager.update_asset("BV1aaaa", "标题", "video", 0, "./downloads/x [BV1aaaa]", source="收藏夹")

    record = manager.get_asset("BV1aaaa")

    assert record["fail_count"] == 0
    assert record["last_fail"] is None
    manager.close()


def test_record_and_reset_download_failures(tmp_path):
    manager = DatabaseManager(tmp_path / "archive.db")
    manager.update_asset("BV1aaaa", "标题", "video", 0, "./downloads/x [BV1aaaa]", source="收藏夹")

    assert manager.record_download_failure("BV1aaaa", "404") == 1
    assert manager.record_download_failure("BV1aaaa") == 2
    assert manager.record_download_failure("BV1aaaa", "地区限制") == 3

    record = manager.get_asset("BV1aaaa")
    assert record["fail_count"] == 3
    assert record["last_fail"] is not None
    # last_fail 与 last_check 同格式，可被退避策略直接解析
    assert parse_last_fail(record["last_fail"]) is not None
    assert should_skip_for_backoff(record) is True

    assert manager.reset_download_failures("BV1aaaa") is True
    record = manager.get_asset("BV1aaaa")
    assert record["fail_count"] == 0
    assert record["last_fail"] is None
    assert should_skip_for_backoff(record) is False
    manager.close()


def test_failure_on_never_downloaded_asset_creates_minimal_row(tmp_path):
    """首次就失败（404/付费）时没有行可更新，账本必须能自己建档。"""
    manager = DatabaseManager(tmp_path / "archive.db")

    assert manager.record_download_failure("BV1fail", "源端 404") == 1

    record = manager.get_asset("BV1fail")
    assert record["fail_count"] == 1
    assert record["last_fail"] is not None
    # 最小行不含归档信息：path 为空 → 后续仍会被判定为"未完成"并允许重试
    assert record["path"] is None
    assert record["status"] == 0
    manager.close()


def test_reset_without_record_does_not_create_row(tmp_path):
    manager = DatabaseManager(tmp_path / "archive.db")

    assert manager.reset_download_failures("BV1missing") is False
    assert manager.get_asset("BV1missing") is None
    manager.close()


def test_legacy_database_migration_adds_failure_columns(tmp_path):
    """旧库（无 fail_count/last_fail）升级后新列默认 0/NULL，原有行不变。"""
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE assets (
                bvid TEXT PRIMARY KEY NOT NULL,
                title TEXT,
                type TEXT,
                status INTEGER NOT NULL DEFAULT 0,
                path TEXT,
                last_check TEXT,
                p_count INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        connection.execute(
            "INSERT INTO assets (bvid, title, type, status, path, last_check, p_count) "
            "VALUES ('BV1legacy', '旧资产', 'video', 0, './downloads/x [BV1legacy]', "
            "'2024-01-01 00:00:00', 1)"
        )

    manager = DatabaseManager(db_path)
    columns = {
        row[1] for row in manager.conn.execute("PRAGMA table_info(assets)").fetchall()
    }
    assert {"fail_count", "last_fail"} <= columns

    record = manager.get_asset("BV1legacy")
    assert record["title"] == "旧资产"
    assert record["fail_count"] == 0
    assert record["last_fail"] is None

    # 迁移后账本可用
    assert manager.record_download_failure("BV1legacy") == 1
    manager.close()


# ---------- 扫描端接入 ----------


class LedgerDatabase:
    """记录失败账本调用的最小数据库替身。"""

    def __init__(self):
        self.records = {}
        self.failure_calls = []
        self.reset_calls = []
        self.writes = []

    def get_asset(self, key):
        return self.records.get(key)

    def update_asset(self, key, title, asset_type, status, path, p_count=1, source=None):
        self.records[key] = {
            "bvid": key,
            "title": title,
            "type": asset_type,
            "status": status,
            "path": path,
            "last_check": None,
            "p_count": p_count,
            "source": source,
            "fail_count": 0,
            "last_fail": None,
        }
        self.writes.append(key)

    def update_last_check(self, key):
        pass

    def record_download_failure(self, key, reason=""):
        self.failure_calls.append((key, reason))
        record = self.records.setdefault(
            key,
            {
                "bvid": key,
                "title": None,
                "type": None,
                "status": 0,
                "path": None,
                "last_check": None,
                "p_count": 1,
                "fail_count": 0,
                "last_fail": None,
            },
        )
        record["fail_count"] = int(record.get("fail_count") or 0) + 1
        record["last_fail"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return record["fail_count"]

    def reset_download_failures(self, key):
        self.reset_calls.append(key)
        record = self.records.get(key)
        if record is None:
            return False
        record["fail_count"] = 0
        record["last_fail"] = None
        return True


class CountingDownloader:
    """固定成功的下载器替身（不写文件，只为统计调用次数）。"""

    def __init__(self, succeed=True):
        self.calls = []
        self.succeed = succeed

    def download_video(self, url, save_dir, file_name, cookie_file_path):
        self.calls.append(file_name)
        return self.succeed


class SingleVideoParser:
    def __init__(self, item):
        self.item = item

    async def get_favorite_list(self, fav_id, page):
        return ([dict(self.item)], False) if page == 1 else ([], False)

    async def check_multi_p(self, bvid):
        return False, [{"page": 1, "part": "单集"}]


def ledger_config():
    return {
        "system": {
            "cookie_path": "cookie.json",
            "min_disk_gb": 0,
            "max_downloads_per_run": 0,
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


def build_ledger_scanner(tmp_path, database, succeed, monkeypatch):
    scanner = FavScanner(
        ledger_config(),
        credential=object(),
        db=database,
        path_mgr=PathManager(str(tmp_path), plex_mode=True),
    )
    scanner.parser = SingleVideoParser(
        {
            "title": "失败视频",
            "bvid": "BV1fail",
            "aid": 1,
            "id": 1,
            "type": "video",
        }
    )
    scanner.downloader = CountingDownloader(succeed=succeed)
    monkeypatch.setattr(ScannerBase, "_login_gate_open", lambda self: True)
    # 封面与 NFO 是布局细节：替身下载器不产出文件，这里替换掉以聚焦账本。
    monkeypatch.setattr(
        "app.scheduler.sources.download.MetadataGenerator.copy_artwork",
        lambda *args, **kwargs: "/archive/poster.jpg",
    )
    monkeypatch.setattr(
        "app.scheduler.sources.download.MetadataGenerator.create_nfo",
        lambda *args, **kwargs: "/archive/video.nfo",
    )
    return scanner


def test_failed_download_is_recorded_in_the_ledger(monkeypatch, tmp_path, capsys):
    database = LedgerDatabase()
    scanner = build_ledger_scanner(tmp_path, database, False, monkeypatch)

    asyncio.run(scanner.scan_favorite(99, "测试收藏夹"))

    assert database.failure_calls and database.failure_calls[0][0] == "BV1fail"
    assert "已登记下载失败" in capsys.readouterr().out


def test_asset_in_cooldown_is_skipped_with_a_reason(monkeypatch, tmp_path, capsys):
    database = LedgerDatabase()
    database.records["BV1fail"] = {
        "bvid": "BV1fail",
        "title": "失败视频",
        "type": "video",
        "status": 0,
        "path": None,
        "last_check": None,
        "p_count": 1,
        "fail_count": 2,
        "last_fail": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    scanner = build_ledger_scanner(tmp_path, database, True, monkeypatch)

    asyncio.run(scanner.scan_favorite(99, "测试收藏夹"))

    # 冷却期内不下载，且原因打印出来（不静默）
    assert scanner.downloader.calls == []
    assert database.writes == []
    output = capsys.readouterr().out
    assert "跳过失败冷却中的资产" in output
    assert "连续失败 2 次" in output


def test_successful_download_resets_the_ledger(monkeypatch, tmp_path):
    database = LedgerDatabase()
    database.records["BV1fail"] = {
        "bvid": "BV1fail",
        "title": "失败视频",
        "type": "video",
        "status": 0,
        "path": None,
        "last_check": None,
        "p_count": 1,
        # 冷却早已过期：本轮应当重试并成功
        "fail_count": 1,
        "last_fail": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
    }
    scanner = build_ledger_scanner(tmp_path, database, True, monkeypatch)

    asyncio.run(scanner.scan_favorite(99, "测试收藏夹"))

    assert database.reset_calls == ["BV1fail"]


def test_failure_row_without_path_is_not_marked_protected(monkeypatch, tmp_path):
    """账本的最小行没有本地文件，源端失效时不该被写成"孤本保护"。"""
    database = LedgerDatabase()
    database.records["BV1fail"] = {
        "bvid": "BV1fail",
        "title": "已失效视频",
        "type": "unknown",
        "status": 0,
        "path": None,
        "last_check": None,
        "p_count": 1,
        "fail_count": 1,
        "last_fail": None,
    }
    scanner = build_ledger_scanner(tmp_path, database, True, monkeypatch)
    scanner.parser = SingleVideoParser(
        {"title": "已失效视频", "bvid": "BV1fail", "aid": 1, "id": 1, "type": "video"}
    )

    asyncio.run(scanner.scan_favorite(99, "测试收藏夹"))

    # 没有本地文件就没有孤本可保护：状态保持原样，也不写回路径
    assert database.records["BV1fail"]["status"] == 0
    assert database.records["BV1fail"]["path"] is None
    assert database.writes == []


def test_forced_redownload_clears_the_failure_ledger(tmp_path):
    """WebUI 手动重下必须能立刻绕过退避。"""
    database = LedgerDatabase()
    database.records["BV1fail"] = {
        "bvid": "BV1fail",
        "fail_count": 4,
        "last_fail": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    scanner = FavScanner(
        ledger_config(),
        credential=object(),
        db=database,
        path_mgr=PathManager(str(tmp_path), plex_mode=True),
    )

    keys = scanner.request_redownload("BV1fail")

    assert keys == {"BV1fail"}
    assert database.reset_calls == ["BV1fail"]
    # 重下登记后账本归零，冷却判定不再拦住这一轮
    assert should_skip_for_backoff(database.records["BV1fail"]) is False
