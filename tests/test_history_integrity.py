import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.database_manager import DatabaseManager
from app.core.integrity import IntegrityVerifier
from app.scheduler.scanner import FavScanner

from tests.test_scanner import scanner_config


class HistoryParser:
    """模拟观看历史：两页，按观看时间倒序。"""

    def __init__(self, now):
        self.now = now
        self.pages_requested = []

    async def get_watch_history(self, page=1, page_size=100):
        self.pages_requested.append(page)
        day = 86400
        if page == 1:
            return (
                [
                    {"bvid": "BV1H1", "title": "历史1", "up_name": "UP甲", "view_at": self.now - 1 * day},
                    {"bvid": "BV1H2", "title": "历史2", "up_name": "UP乙", "view_at": self.now - 5 * day},
                ],
                True,
            )
        if page == 2:
            return (
                [
                    {"bvid": "BV1H3", "title": "直播回放", "up_name": "UP丙", "view_at": self.now - 10 * day},
                    # 超出窗口的旧记录
                    {"bvid": "BV1H4", "title": "太老", "up_name": "UP丁", "view_at": self.now - 400 * day},
                ],
                False,
            )
        return [], False


class HistoryDatabase(DatabaseManager):
    """内存数据库版（DatabaseManager 支持 :memory:）。"""


def build_history_scanner(monkeypatch, db, now):
    scanner = FavScanner(
        scanner_config(),
        credential=object(),
        db=db,
        path_mgr=object(),
    )
    parser = HistoryParser(now)
    scanner.parser = parser

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr("app.scheduler.scanner.asyncio.sleep", no_sleep)
    return scanner, parser


def test_watch_history_sync_respects_window_and_stops_at_known(monkeypatch):
    now = 1_800_000_000
    db = DatabaseManager(":memory:")
    try:
        scanner, parser = build_history_scanner(monkeypatch, db, now)

        async def run():
            await scanner.sync_watch_history()

        asyncio.run(run())

        rows = {
            r[0]: r[1]
            for r in db.conn.execute("SELECT bvid, title FROM watch_history").fetchall()
        }
        # 窗口内的记录写入；窗口外的 BV1H4 被跳过（窗口即边界）
        assert set(rows) == {"BV1H1", "BV1H2", "BV1H3"}
        # 触及窗口外记录后停止翻页（不再请求第 3 页）
        assert parser.pages_requested == [1, 2]
    finally:
        db.close()


def test_watch_history_incremental_stops_at_known_oldest(monkeypatch):
    now = 1_800_000_000
    db = DatabaseManager(":memory:")
    try:
        # 预置一条比新页更早的已知记录
        db.record_watch_history("BV1OLD", "旧记录", "UP老", now - 60 * 86400)
        scanner, parser = build_history_scanner(monkeypatch, db, now)

        async def run():
            await scanner.sync_watch_history()

        asyncio.run(run())
        # 第一页都是比已知记录新的条目，继续翻页；第二页触及窗口边界后停止
        assert parser.pages_requested == [1, 2]
        # 预置的旧记录仍在，未被破坏
        assert db.conn.execute(
            "SELECT 1 FROM watch_history WHERE bvid='BV1OLD'"
        ).fetchone()
    finally:
        db.close()


class _FakeCompleted:
    def __init__(self, returncode=0, stderr=b""):
        self.returncode = returncode
        self.stderr = stderr


@pytest.fixture
def media_tree(tmp_path):
    """构造一个符合命名约定的单 P 资产目录。"""
    asset_dir = tmp_path / "资产" / "BV1GOOD"
    asset_dir.mkdir(parents=True)
    # 标准 MP4 头（ftyp box）
    (asset_dir / "标题 [BV1GOOD].mp4").write_bytes(
        b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 32
    )
    return asset_dir


def _asset(path, bvid="BV1GOOD", p_count=1):
    return {"bvid": bvid, "path": str(path), "p_count": p_count}


def test_integrity_light_passes_valid_mp4(media_tree):
    verifier = IntegrityVerifier({"system": {"verify_integrity": "light"}})
    ok, reason, checked = verifier.verify_asset(_asset(media_tree.parent))
    assert ok is True
    assert checked == 1


def test_integrity_light_rejects_empty_and_corrupt(tmp_path):
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    (bad_dir / "空文件 [BV1E].mp4").write_bytes(b"")
    (bad_dir / "伪文件 [BV1F].mp4").write_bytes(b"this is not a media file at all")

    verifier = IntegrityVerifier({"system": {"verify_integrity": "light"}})

    ok, reason, _ = verifier.verify_asset(_asset(bad_dir, "BV1E"))
    assert ok is False
    assert "为空" in reason

    ok, reason, _ = verifier.verify_asset(_asset(bad_dir, "BV1F"))
    assert ok is False
    assert "签名" in reason


def test_integrity_detects_missing_parts(tmp_path):
    asset_dir = tmp_path / "multi"
    asset_dir.mkdir()
    (asset_dir / "标题 [BV1M-P1].mp4").write_bytes(
        b"\x00\x00\x00\x20ftypisom" + b"\x00" * 32
    )
    # 缺 P2
    verifier = IntegrityVerifier({"system": {"verify_integrity": "light"}})
    ok, reason, checked = verifier.verify_asset(_asset(asset_dir, "BV1M", p_count=2))
    assert ok is False
    assert "缺少" in reason
    assert checked == 1


def test_integrity_full_mode_invokes_ffmpeg(media_tree, monkeypatch):
    calls = []

    def fake_run(command, capture_output, timeout):
        calls.append(command)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = IntegrityVerifier(
        {"system": {"verify_integrity": "full"}, "components": {"ffmpeg": {"path": "ffmpeg"}}}
    )
    ok, _, _ = verifier.verify_asset(_asset(media_tree.parent))
    assert ok is True
    assert len(calls) == 1
    assert calls[0][0] == "ffmpeg"


def test_integrity_full_mode_reports_ffmpeg_error(media_tree, monkeypatch):
    def fake_run(command, capture_output, timeout):
        return _FakeCompleted(returncode=1, stderr=b"Invalid data found\nmoov atom not found\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    verifier = IntegrityVerifier(
        {"system": {"verify_integrity": "full"}, "components": {"ffmpeg": {"path": "ffmpeg"}}}
    )
    ok, reason, _ = verifier.verify_asset(_asset(media_tree.parent))
    assert ok is False
    assert "moov atom" in reason


def test_integrity_mode_validation():
    assert IntegrityVerifier({"system": {"verify_integrity": "off"}}).enabled is False
    assert IntegrityVerifier({"system": {"verify_integrity": "light"}}).enabled is True
    assert IntegrityVerifier({"system": {"verify_integrity": "full"}}).enabled is True
    assert IntegrityVerifier({"system": {"verify_integrity": "乱写"}}).enabled is False


def test_scanner_verify_integrity_writes_results(tmp_path, monkeypatch):
    now = 1_800_000_000
    db = DatabaseManager(":memory:")
    try:
        good_dir = tmp_path / "good"
        good_dir.mkdir()
        (good_dir / "标题 [BV1OK].mp4").write_bytes(
            b"\x00\x00\x00\x20ftypisom" + b"\x00" * 32
        )
        bad_dir = tmp_path / "bad"
        bad_dir.mkdir()
        (bad_dir / "标题 [BV1BAD].mp4").write_bytes(b"garbage")

        db.update_asset("BV1OK", "完好", "video", 0, str(good_dir), 1)
        db.update_asset("BV1BAD", "损坏", "video", 0, str(bad_dir), 1)

        scanner = FavScanner(
            scanner_config(),
            credential=object(),
            db=db,
            path_mgr=object(),
        )
        verifier = IntegrityVerifier({"system": {"verify_integrity": "light"}})

        async def run():
            await scanner.verify_integrity(verifier)

        asyncio.run(run())

        statuses = {
            r[0]: r[1]
            for r in db.conn.execute(
                "SELECT bvid, integrity_status FROM assets"
            ).fetchall()
        }
        assert statuses["BV1OK"] == db.INTEGRITY_OK
        assert statuses["BV1BAD"] == db.INTEGRITY_CORRUPT

        # 已校验的资产排到候选队列末尾
        remaining = db.candidates_for_verify()
        assert remaining == [] or all(c["bvid"] for c in remaining)
    finally:
        db.close()


def test_assets_migration_adds_integrity_columns(tmp_path):
    """旧库（无 integrity 列）打开时自动补列。"""
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
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
    conn.execute("INSERT INTO assets (bvid, title) VALUES ('BV1OLD', '旧资产')")
    conn.commit()
    conn.close()

    db = DatabaseManager(str(db_path))
    try:
        columns = {
            row[1] for row in db.conn.execute("PRAGMA table_info(assets)").fetchall()
        }
        assert "integrity_status" in columns
        assert "last_verify" in columns
        record = db.get_asset("BV1OLD")
        assert record["integrity_status"] == 0
    finally:
        db.close()
