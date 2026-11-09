"""词云浏览入口测试。

词云是下载时写在媒体旁边的 `<stem>.wordcloud.svg`，WebUI 现在要把它
暴露出来。这组用例锁住两件事：能找到它，以及永远不把下载根目录以外的
文件交出去。
"""

import sqlite3

from app.webui.service import WebService


def _service(tmp_path, asset_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"system:\n  db_path: archive.db\n  download_path: {tmp_path / 'downloads'}\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "archive.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE assets (bvid TEXT PRIMARY KEY, title TEXT, type TEXT, "
            "status INTEGER, path TEXT, last_check TEXT, p_count INTEGER)"
        )
        conn.execute(
            "INSERT INTO assets (bvid, title, type, status, path, last_check, p_count)"
            " VALUES ('BV1', '资产', 'video', 0, ?, '2026-10-20T00:00:00+08:00', 1)",
            (str(asset_path),),
        )
    return WebService(
        project_root=tmp_path,
        config_path=config_path,
        db_path=db_path,
        version="1.7.1",
    )


def _asset_dir(tmp_path):
    asset_dir = tmp_path / "downloads" / "UP 主" / "标题 [BV1]"
    asset_dir.mkdir(parents=True)
    return asset_dir


def test_wordcloud_side_car_is_found(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    svg = asset_dir / "标题 [BV1].wordcloud.svg"
    svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    service = _service(tmp_path, asset_dir)

    assert service.wordcloud_path("BV1") == svg.resolve()


def test_missing_wordcloud_returns_none(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    service = _service(tmp_path, asset_dir)

    assert service.wordcloud_path("BV1") is None


def test_wordcloud_outside_the_download_root_is_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    svg = outside / "x.wordcloud.svg"
    svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    service = _service(tmp_path, outside)

    assert service.wordcloud_path("BV1") is None


def test_unknown_asset_returns_none(tmp_path):
    asset_dir = _asset_dir(tmp_path)
    service = _service(tmp_path, asset_dir)

    assert service.wordcloud_path("BV-does-not-exist") is None
