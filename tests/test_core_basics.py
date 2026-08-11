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


def test_path_manager_plex_mode_controls_multi_part_layout():
    video_dir = os.path.join("archive", "Video [BV123]")
    plex_path_mgr = PathManager("archive", plex_mode=True)
    flat_path_mgr = PathManager("archive", plex_mode=False)

    plex_dir, plex_name = plex_path_mgr.get_video_output(
        video_dir,
        "Video",
        "BV123",
        part_number=2,
        part_title="第二/集",
        part_count=3,
    )
    flat_dir, flat_name = flat_path_mgr.get_video_output(
        video_dir,
        "Video",
        "BV123",
        part_number=2,
        part_title="第二/集",
        part_count=3,
    )

    assert os.path.basename(plex_dir) == "Season 01"
    assert plex_name.startswith("S01E02 - 第二_集")
    assert plex_name.endswith("[BV123-P2]")
    assert flat_dir == video_dir
    assert flat_name.startswith("P02 - 第二_集")
    assert flat_name.endswith("[BV123-P2]")


def test_path_manager_single_part_layout_is_unchanged_by_plex_mode():
    video_dir = os.path.join("archive", "Video [BV123]")

    enabled = PathManager("archive", plex_mode=True).get_video_output(
        video_dir,
        "Video",
        "BV123",
    )
    disabled = PathManager("archive", plex_mode=False).get_video_output(
        video_dir,
        "Video",
        "BV123",
    )

    assert enabled == disabled == (video_dir, "Video [BV123]")


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        (".", "Untitled"),
        ("..", "Untitled"),
        ("CON", "_CON"),
        ("lpt1.txt", "_lpt1.txt"),
        ("title. ", "title"),
    ],
)
def test_path_manager_rejects_unsafe_cross_platform_components(raw_name, expected):
    assert PathManager.sanitize_filename(raw_name) == expected


def test_path_manager_limits_long_source_directory_with_stable_hash(tmp_path):
    path_manager = PathManager(str(tmp_path / "archive"))
    first_name = "超长收藏夹" * 30 + "甲"
    second_name = "超长收藏夹" * 30 + "乙"

    first_path = path_manager.get_video_dir(first_name, "视频", "BV123")
    repeated_path = path_manager.get_video_dir(first_name, "视频", "BV123")
    second_path = path_manager.get_video_dir(second_name, "视频", "BV123")
    first_component = os.path.basename(os.path.dirname(first_path))
    second_component = os.path.basename(os.path.dirname(second_path))

    assert first_path == repeated_path
    assert len(first_component) <= PathManager.SOURCE_DIR_MAX_LENGTH
    assert first_component != second_component
    assert "~" in first_component


@pytest.mark.parametrize("plex_mode", [True, False])
def test_path_manager_budgets_media_stem_against_full_path(tmp_path, plex_mode):
    long_root = tmp_path / "archive-root"
    path_manager = PathManager(str(long_root), plex_mode=plex_mode)
    video_dir = path_manager.get_video_dir(
        "收藏夹" * 40,
        "视频标题" * 40,
        "BV1234567890",
    )
    media_dir, file_name = path_manager.get_video_output(
        video_dir,
        "视频标题" * 40,
        "BV1234567890",
        part_number=12,
        part_title="分集标题" * 40,
        part_count=20,
    )

    stem_path = os.path.abspath(os.path.join(media_dir, file_name))
    assert (
        len(stem_path) + PathManager.OUTPUT_SUFFIX_RESERVE
        <= PathManager.MAX_PATH_LENGTH
    )
    assert len(f"{stem_path}.f12345.mp4.part") <= PathManager.MAX_PATH_LENGTH
    assert file_name.endswith("[BV1234567890-P12]")


def test_path_manager_rejects_root_that_cannot_preserve_unique_identifiers(tmp_path):
    too_long_root = tmp_path / ("x" * PathManager.MAX_PATH_LENGTH)

    with pytest.raises(ValueError, match="归档根目录过长"):
        PathManager(str(too_long_root))


def test_truncate_filename_never_silently_truncates_unique_identifier():
    suffix_length = len(" [BV123]")

    with pytest.raises(ValueError, match="唯一标识"):
        PathManager.truncate_filename("标题", "BV123", max_len=suffix_length)


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


def test_metadata_generator_creates_matching_episode_and_show_nfos(tmp_path):
    video_info = {
        "title": "测试多P",
        "bvid": "BV123",
        "up_name": "测试UP",
        "intro": "简介",
        "pubtime": 1704067200,
    }
    season_dir = tmp_path / "Season 01"
    file_stem = "S01E02 - 第二集 [BV123-P2]"

    episode_path = MetadataGenerator.create_episode_nfo(
        video_info,
        str(season_dir),
        file_stem,
        2,
        "第二集",
    )
    show_path = MetadataGenerator.create_tvshow_nfo(video_info, str(tmp_path))

    assert episode_path == str(season_dir / f"{file_stem}.nfo")
    episode = ET.parse(episode_path).getroot()
    assert episode.tag == "episodedetails"
    assert episode.findtext("title") == "第二集"
    assert episode.findtext("showtitle") == "测试多P"
    assert episode.findtext("season") == "1"
    assert episode.findtext("episode") == "2"
    assert episode.findtext("uniqueid") == "BV123-P2"
    show = ET.parse(show_path).getroot()
    assert show.tag == "tvshow"
    assert show.findtext("title") == "测试多P"


def test_metadata_generator_copies_ytdlp_thumbnail_to_standard_artwork_name(tmp_path):
    media_dir = tmp_path / "Season 01"
    media_dir.mkdir()
    source = media_dir / "S01E01 - 第一集.jpg"
    source.write_bytes(b"jpeg data")
    target = tmp_path / "poster.jpg"
    target.write_bytes(b"old poster")

    result = MetadataGenerator.copy_artwork(
        str(media_dir),
        "S01E01 - 第一集",
        str(target),
    )

    assert result == str(target)
    assert target.read_bytes() == b"jpeg data"
