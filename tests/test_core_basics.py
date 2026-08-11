import os
import sqlite3
import xml.etree.ElementTree as ET

import pytest

from app.core.database_manager import DatabaseManager
from app.core.metadata import MetadataGenerator
from app.core.path_manager import PathManager


def test_path_manager_sanitizes_and_truncates_video_directory():
    path_mgr = PathManager("/archive")

    path = path_mgr.get_video_dir("收藏/夹", "很长" * 40 + ":标题", "BV123")
    video_dir_name = os.path.basename(path)
    favorite_dir_name = os.path.basename(os.path.dirname(path))

    assert favorite_dir_name == "收藏_夹"
    assert video_dir_name.endswith(" [BV123]")
    assert len(video_dir_name) <= 80
    assert ":" not in video_dir_name


def test_database_manager_stores_and_updates_asset(tmp_path):
    db = DatabaseManager(str(tmp_path / "data" / "archive.db"))

    db.update_asset("BV123", "标题", "video", 0, "/archive/BV123", p_count=2)
    db.update_status("BV123", 2)
    asset = db.get_asset("BV123")
    db.close()

    assert asset["bvid"] == "BV123"
    assert asset["title"] == "标题"
    assert asset["type"] == "video"
    assert asset["status"] == 2
    assert asset["path"] == "/archive/BV123"
    assert asset["p_count"] == 2


@pytest.mark.parametrize("invalid_key", [None, "", "   "])
def test_database_manager_rejects_empty_asset_keys(tmp_path, invalid_key):
    db = DatabaseManager(str(tmp_path / "data" / "archive.db"))

    with pytest.raises(ValueError, match="主键不能为空"):
        db.get_asset(invalid_key)
    with pytest.raises(ValueError, match="主键不能为空"):
        db.update_asset(invalid_key, "标题", "video", 0, "/archive")

    db.close()


def test_database_manager_migrates_legacy_columns_idempotently(tmp_path):
    db_path = tmp_path / "data" / "legacy.db"
    db_path.parent.mkdir()
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE assets (
            bvid TEXT PRIMARY KEY,
            title TEXT,
            type TEXT,
            status INTEGER,
            path TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO assets (bvid, title, type, status, path) VALUES (?, ?, ?, ?, ?)",
        ("BV123", "旧记录", "video", 0, "/archive/BV123"),
    )
    connection.commit()
    connection.close()

    db = DatabaseManager(str(db_path))
    asset = db.get_asset("BV123")
    columns = {
        row[1] for row in db.conn.execute("PRAGMA table_info(assets)").fetchall()
    }
    schema_version = db.conn.execute("PRAGMA user_version").fetchone()[0]
    db.close()

    assert {"last_check", "p_count"} <= columns
    assert asset["last_check"] is None
    assert asset["p_count"] == 1
    assert schema_version == DatabaseManager.SCHEMA_VERSION

    reopened = DatabaseManager(str(db_path))
    assert reopened.get_asset("BV123")["p_count"] == 1
    reopened.close()


def test_database_manager_preserves_legacy_invalid_rows_with_unique_keys(tmp_path):
    db_path = tmp_path / "data" / "legacy-invalid.db"
    db_path.parent.mkdir()
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE assets (
            bvid TEXT PRIMARY KEY,
            title TEXT,
            type TEXT,
            status INTEGER,
            path TEXT,
            last_check TEXT,
            p_count INTEGER
        )
        """
    )
    connection.execute(
        "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?)",
        (None, "空键一", "unknown", 1, "/archive/one", None, None),
    )
    connection.execute(
        "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("", "空键二", "unknown", 1, "/archive/two", None, 0),
    )
    connection.commit()
    connection.close()

    db = DatabaseManager(str(db_path))
    rows = db.conn.execute(
        "SELECT bvid, p_count FROM assets ORDER BY title"
    ).fetchall()
    db.close()

    assert len(rows) == 2
    assert len({row[0] for row in rows}) == 2
    assert all(row[0].startswith("legacy-invalid-") for row in rows)
    assert all(row[1] == 1 for row in rows)


def test_database_migration_rolls_back_schema_when_repair_fails(tmp_path):
    class FailingMigrationManager(DatabaseManager):
        def _repair_legacy_rows(self):
            raise RuntimeError("forced migration failure")

    db_path = tmp_path / "data" / "rollback.db"
    db_path.parent.mkdir()
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE assets (bvid TEXT PRIMARY KEY, title TEXT)"
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="forced migration failure"):
        FailingMigrationManager(str(db_path))

    connection = sqlite3.connect(db_path)
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(assets)").fetchall()
    }
    connection.close()
    assert columns == {"bvid", "title"}


def test_database_manager_adds_unique_constraint_to_legacy_bvid_column(tmp_path):
    db_path = tmp_path / "data" / "non-unique.db"
    db_path.parent.mkdir()
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE assets (bvid TEXT, title TEXT)")
    connection.execute("INSERT INTO assets VALUES ('BV123', '旧记录')")
    connection.commit()
    connection.close()

    db = DatabaseManager(str(db_path))
    db.update_asset("BV123", "新记录", "video", 0, "/archive/BV123")
    rows = db.conn.execute(
        "SELECT bvid, title FROM assets WHERE bvid='BV123'"
    ).fetchall()
    db.close()

    assert rows == [("BV123", "新记录")]


def test_database_manager_rejects_duplicate_legacy_bvid_rows(tmp_path):
    db_path = tmp_path / "data" / "duplicate.db"
    db_path.parent.mkdir()
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE assets (bvid TEXT, title TEXT)")
    connection.execute("INSERT INTO assets VALUES ('BV123', '一')")
    connection.execute("INSERT INTO assets VALUES ('BV123', '二')")
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="重复 bvid"):
        DatabaseManager(str(db_path))


def test_metadata_generator_creates_plex_nfo(tmp_path):
    MetadataGenerator.create_nfo(
        {
            "title": "测试标题",
            "bvid": "BV123",
            "up_name": "测试UP",
            "intro": "简介",
            "pubtime": 1704067200,
        },
        str(tmp_path),
        status="Active",
    )

    nfo_path = tmp_path / "测试标题.nfo"
    root = ET.parse(nfo_path).getroot()

    assert root.findtext("title") == "测试标题"
    assert root.findtext("uniqueid") == "BV123"
    assert root.findtext("studio") == "测试UP"
    assert root.findtext("plot") == "简介"
    assert root.findtext("premiered") == "2024-01-01"
