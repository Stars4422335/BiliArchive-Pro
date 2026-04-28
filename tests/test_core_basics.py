import xml.etree.ElementTree as ET

from app.core.database_manager import DatabaseManager
from app.core.metadata import MetadataGenerator
from app.core.path_manager import PathManager


def test_path_manager_sanitizes_and_truncates_video_directory():
    path_mgr = PathManager("/archive")

    path = path_mgr.get_video_dir("收藏/夹", "很长" * 40 + ":标题", "BV123")

    assert path.startswith("/archive/收藏_夹/")
    assert path.endswith(" [BV123]")
    assert len(path.split("/")[-1]) <= 80
    assert ":" not in path.split("/")[-1]


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
