"""v1.9.1 新增能力：存量库升级无损、来源筛选、配置热重载。

数据安全红线：任何迁移都只加列/补空值，绝不删除、改写或重置现有行。
本文件里的升级测试用 v1.9.0 真实结构（无 source 列）+ 多状态数据行，
逐字段断言升级前后完全一致。
"""

import json
import sqlite3

import pytest
import yaml
from fastapi.testclient import TestClient

from app.core.commands import (
    COMMAND_RELOAD_CONFIG,
    SUPPORTED_COMMANDS,
    dispatch_commands,
)
from app.core.database_manager import DatabaseManager
from app.webui import create_app
from app.webui.queries.settings import CONFIG_SCHEMA, effect_for, effect_summary

# ---------- 存量库升级无损 ----------


def _build_v190_database(path):
    """创建与 v1.9.0 一致的库结构（无 source 列）并写入多状态数据。"""
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE assets ("
        " bvid TEXT PRIMARY KEY NOT NULL CHECK (length(trim(bvid)) > 0),"
        " title TEXT, type TEXT, status INTEGER NOT NULL DEFAULT 0,"
        " path TEXT, last_check TEXT, p_count INTEGER NOT NULL DEFAULT 1)"
    )
    connection.executemany(
        "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("BV1AAA", "已归档视频A", "video", 0, "./downloads/默认收藏夹/视频A [BV1AAA]", "2026-11-09 10:00:00", 1),
            ("BV1BBB", "已归档多P视频", "video", 0, "./downloads/默认收藏夹/视频B [BV1BBB]", "2026-11-09 11:00:00", 5),
            ("CV1CCC", "已归档专栏", "article", 0, "./downloads/我的专栏/专栏C [CV1CCC]", "2026-11-09 12:00:00", 1),
            ("BV1DDD", "失效视频", "unknown", 1, "./downloads/默认收藏夹/已失效视频 [BV1DDD]", "2026-11-09 13:00:00", 1),
            ("BV1EEE", "孤本保护视频", "video", 2, "./downloads/[源端已删] 默认收藏夹/视频E [BV1EEE]", "2026-11-09 14:00:00", 1),
            ("BV1FFF", "无路径资产", "video", 0, None, None, 1),
        ],
    )
    connection.commit()
    connection.close()


def test_upgrade_from_v190_database_is_lossless(tmp_path):
    db_path = tmp_path / "archive.db"
    _build_v190_database(db_path)

    before = {}
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    for row in connection.execute("SELECT * FROM assets ORDER BY bvid"):
        before[row["bvid"]] = dict(row)
    connection.close()
    assert "source" not in next(iter(before.values()))

    manager = DatabaseManager(db_path)  # 触发迁移 + 回填

    columns = {
        row[1] for row in manager.conn.execute("PRAGMA table_info(assets)")
    }
    assert "source" in columns
    assert manager.conn.execute("PRAGMA user_version").fetchone()[0] == 2

    after = {}
    for row in manager.conn.execute(
        "SELECT bvid, title, type, status, path, last_check, p_count, source FROM assets ORDER BY bvid"
    ):
        after[row[0]] = {
            "bvid": row[0], "title": row[1], "type": row[2], "status": row[3],
            "path": row[4], "last_check": row[5], "p_count": row[6], "source": row[7],
        }

    # 行集合不变
    assert set(after) == set(before)
    for bvid, old_row in before.items():
        new_row = after[bvid]
        # 现有字段逐字段无损
        for field in ("title", "type", "status", "path", "last_check", "p_count"):
            assert new_row[field] == old_row[field], f"{bvid}.{field}"
        # source 只补空值
        if bvid == "BV1FFF":
            assert new_row["source"] is None  # 无路径不回填
        else:
            expected = {
                "BV1AAA": "默认收藏夹",
                "BV1BBB": "默认收藏夹",
                "CV1CCC": "我的专栏",
                "BV1DDD": "默认收藏夹",
                "BV1EEE": "[源端已删] 默认收藏夹",
            }[bvid]
            assert new_row["source"] == expected, f"{bvid} source 回填"

    # 幂等：二次打开不重复回填、不改动
    manager.conn.close()
    manager2 = DatabaseManager(db_path)
    after2 = {
        row[0]: {
            "bvid": row[0], "title": row[1], "type": row[2], "status": row[3],
            "path": row[4], "last_check": row[5], "p_count": row[6], "source": row[7],
        }
        for row in manager2.conn.execute(
            "SELECT bvid, title, type, status, path, last_check, p_count, source FROM assets ORDER BY bvid"
        )
    }
    assert after2 == after
    manager2.conn.close()


def test_update_asset_coalesce_keeps_existing_source(tmp_path):
    db_path = tmp_path / "archive.db"
    manager = DatabaseManager(db_path)
    manager.update_asset("BV1AAA", "标题", "video", 0, "./downloads/默认收藏夹/x [BV1AAA]", source="默认收藏夹")
    # 不带 source 的更新不得清掉已有来源
    manager.update_asset("BV1AAA", "新标题", "video", 0, "./downloads/默认收藏夹/x [BV1AAA]")
    row = manager.conn.execute(
        "SELECT title, source FROM assets WHERE bvid='BV1AAA'"
    ).fetchone()
    assert row[0] == "新标题"
    assert row[1] == "默认收藏夹"
    # 显式新 source 可以覆盖
    manager.update_asset("BV1AAA", "新标题", "video", 0, "./downloads/默认收藏夹/x [BV1AAA]", source="新来源")
    row = manager.conn.execute("SELECT source FROM assets WHERE bvid='BV1AAA'").fetchone()
    assert row[0] == "新来源"
    manager.conn.close()


# ---------- 配置生效分类元数据 ----------


def test_every_schema_key_has_effect_classification():
    for section, allowed in CONFIG_SCHEMA.items():
        if allowed is None:
            assert effect_for(section) in {"immediate", "restart"}
            continue
        for key in allowed:
            assert effect_for(section, key) in {"immediate", "restart"}, f"{section}.{key}"


def test_effect_summary_counts_updates():
    summary = effect_summary(
        {
            "system": {"scan_interval_seconds": 120, "plex_mode": False},
            "favorites": [{"id": 1, "name": "a"}],
        }
    )
    assert summary == {"immediate": 2, "restart": 1}


# ---------- reload_config 命令 ----------


class ReloadScannerStub:
    def __init__(self):
        self.reload_calls = 0
        self.reload_result = True

    def reload_config(self):
        self.reload_calls += 1
        return self.reload_result


def test_reload_config_is_a_supported_command():
    assert COMMAND_RELOAD_CONFIG in SUPPORTED_COMMANDS


def test_dispatch_consumes_reload_command(tmp_path):
    from app.core.commands import CommandChannel

    channel = CommandChannel(tmp_path / "commands.json")
    record = channel.enqueue("reload_config", note="test")
    scanner = ReloadScannerStub()
    import asyncio

    stop = asyncio.run(
        dispatch_commands(channel, scanner, runtime=None, pending_scan=None)
    )
    assert stop is False
    assert scanner.reload_calls == 1
    status = channel.command_status(record["id"])
    assert status["status"] == "done"


def test_dispatch_reports_reload_failure(tmp_path):
    from app.core.commands import CommandChannel

    channel = CommandChannel(tmp_path / "commands.json")
    record = channel.enqueue("reload_config")
    scanner = ReloadScannerStub()
    scanner.reload_result = False
    import asyncio

    asyncio.run(dispatch_commands(channel, scanner, None, None))
    status = channel.command_status(record["id"])
    assert status["status"] == "failed"


# ---------- WebUI：来源筛选与 sources 端点 ----------


@pytest.fixture
def sources_webui_fixture(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = {
        "system": {
            "download_path": str(tmp_path / "downloads"),
            "db_path": str(tmp_path / "archive.db"),
            "cookie_path": str(tmp_path / "cookie.json"),
        },
        "network": {},
        "components": {
            "yt-dlp": {"strategy": "auto", "path": "./bin/yt-dlp"},
            "ffmpeg": {"strategy": "auto", "path": "./bin/ffmpeg"},
        },
    }
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    db_path = tmp_path / "archive.db"
    _build_v190_database(db_path)
    (tmp_path / "downloads").mkdir()
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>app</html>", encoding="utf-8")
    # DatabaseManager 迁移 + 回填（模拟核心引擎已跑过一次）
    manager = DatabaseManager(db_path)
    manager.conn.close()
    app = create_app(
        project_root=tmp_path,
        config_path=config_path,
        db_path=db_path,
        static_dir=static_dir,
    )
    return TestClient(app)


def test_asset_sources_endpoint_lists_backfilled_sources(sources_webui_fixture):
    client = sources_webui_fixture
    body = client.get("/api/assets/sources").json()
    names = {item["source"] for item in body["sources"]}
    assert names == {"默认收藏夹", "我的专栏", "[源端已删] 默认收藏夹"}
    counts = {item["source"]: item["count"] for item in body["sources"]}
    assert counts["默认收藏夹"] == 3


def test_assets_filter_by_source(sources_webui_fixture):
    client = sources_webui_fixture
    body = client.get("/api/assets", params={"source": "默认收藏夹"}).json()
    assert body["total"] == 3
    assert {item["bvid"] for item in body["items"]} == {"BV1AAA", "BV1BBB", "BV1DDD"}
    assert all(item["source"] == "默认收藏夹" for item in body["items"])
    # 来源 + 状态组合筛选
    body2 = client.get("/api/assets", params={"source": "默认收藏夹", "status": "tombstoned"}).json()
    assert body2["total"] == 1
    assert body2["items"][0]["bvid"] == "BV1DDD"


def test_assets_reject_unknown_source_value(sources_webui_fixture):
    client = sources_webui_fixture
    response = client.get("/api/assets", params={"source": "不存在的收藏夹"})
    assert response.status_code == 200
    assert response.json()["total"] == 0


# ---------- WebUI：保存配置返回生效分类并自动入队 reload ----------


def test_put_config_returns_effect_summary_and_enqueues_reload(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = {
        "system": {
            "download_path": str(tmp_path / "downloads"),
            "db_path": str(tmp_path / "archive.db"),
            "cookie_path": str(tmp_path / "cookie.json"),
            "scan_interval_seconds": 3600,
        },
        "network": {},
        "components": {
            "yt-dlp": {"strategy": "auto", "path": "./bin/yt-dlp"},
            "ffmpeg": {"strategy": "auto", "path": "./bin/ffmpeg"},
        },
    }
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    db_path = tmp_path / "archive.db"
    DatabaseManager(db_path).conn.close()
    (tmp_path / "downloads").mkdir()
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>app</html>", encoding="utf-8")
    client = TestClient(
        create_app(project_root=tmp_path, config_path=config_path, db_path=db_path, static_dir=static_dir)
    )

    current = client.get("/api/config").json()
    saved = client.put(
        "/api/config",
        json={
            "revision": current["revision"],
            "config": {
                "system": {"scan_interval_seconds": 120},
                "components": {"yt-dlp": {"strategy": "notify", "path": "./bin/yt-dlp"}},
            },
        },
    )
    assert saved.status_code == 200
    effects = saved.json()["effects"]
    assert effects == {"immediate": 1, "restart": 1}

    # reload 命令落在 db 旁的 commands.json
    inbox = json.loads((tmp_path / "commands.json").read_text(encoding="utf-8"))
    assert any(cmd["command"] == "reload_config" for cmd in inbox["pending"])
