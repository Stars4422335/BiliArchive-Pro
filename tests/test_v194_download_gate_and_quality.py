"""v1.9.4：下载登录门禁、清晰度对比审计、低清清除、下载总开关。"""

import json

import pytest
import yaml
from fastapi.testclient import TestClient

from app.webui import create_app

from app.core.commands import (
    COMMAND_PURGE_LOW_QUALITY,
    SUPPORTED_COMMANDS,
    CommandChannel,
    dispatch_commands,
)
from app.core.database_manager import DatabaseManager
from app.core.quality_audit import QN_TO_HEIGHT, audit_asset, read_local_height

# ---------- ①下载登录门禁 ----------
from app.scheduler.sources.base import login_gate_open


def test_login_gate_blocks_missing_cookie(tmp_path):
    assert login_gate_open(tmp_path / "missing.json") is False


def test_login_gate_blocks_empty_fields(tmp_path):
    cookie = tmp_path / "cookie.json"
    cookie.write_text(json.dumps({"sessdata": "", "dedeuserid": "123"}), encoding="utf-8")
    assert login_gate_open(cookie) is False
    cookie.write_text(json.dumps({"sessdata": "abc", "dedeuserid": None}), encoding="utf-8")
    assert login_gate_open(cookie) is False


def test_login_gate_blocks_invalid_json(tmp_path):
    cookie = tmp_path / "cookie.json"
    cookie.write_text("{not json", encoding="utf-8")
    assert login_gate_open(cookie) is False


def test_login_gate_allows_valid_cookie(tmp_path):
    cookie = tmp_path / "cookie.json"
    cookie.write_text(
        json.dumps({"sessdata": "abc", "dedeuserid": "946974"}), encoding="utf-8"
    )
    assert login_gate_open(cookie) is True


# ---------- ②清晰度对比审计 ----------


def _make_asset_dir(tmp_path, heights):
    """创建带 info.json 的资产目录；heights 为各分集高度列表。"""
    asset_dir = tmp_path / "test 视频 [BV1aaa]"
    asset_dir.mkdir()
    for index, height in enumerate(heights, start=1):
        suffix = "" if len(heights) == 1 else f"-P{index}"
        (asset_dir / f"test 视频 [BV1aaa{suffix}].info.json").write_text(
            json.dumps({"height": height}), encoding="utf-8"
        )
    return asset_dir


def test_read_local_height_single_part(tmp_path):
    asset_dir = _make_asset_dir(tmp_path, [480])
    assert read_local_height(asset_dir) == 480


def test_read_local_height_multi_part_takes_max(tmp_path):
    asset_dir = _make_asset_dir(tmp_path, [480, 1080])
    assert read_local_height(asset_dir, p_count=2) == 1080


def test_read_local_height_dash_requested_formats(tmp_path):
    asset_dir = tmp_path / "dash [BV1bbb]"
    asset_dir.mkdir()
    (asset_dir / "dash [BV1bbb].info.json").write_text(
        json.dumps(
            {
                "requested_formats": [
                    {"height": None, "vcodec": "none"},
                    {"height": 720},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert read_local_height(asset_dir) == 720


def test_read_local_height_missing_info_json(tmp_path):
    empty = tmp_path / "empty [BV1ccc]"
    empty.mkdir()
    assert read_local_height(empty) is None


def test_audit_comparison_logic():
    # 本地 < 源端 → 降级命中
    assert audit_asset(480, 1080)["downgraded"] is True
    # 源端本身就低（用户强调的场景）→ 不命中
    assert audit_asset(480, 480)["downgraded"] is False
    assert audit_asset(1080, 720)["downgraded"] is False
    # 证据不足（任一侧探测失败）→ 不命中
    assert audit_asset(None, 1080)["downgraded"] is False
    assert audit_asset(480, None)["downgraded"] is False


def test_qn_table_covers_common_tiers():
    assert QN_TO_HEIGHT[116] == 1080
    assert QN_TO_HEIGHT[80] == 1080
    assert QN_TO_HEIGHT[32] == 480
    assert QN_TO_HEIGHT[16] == 360


def test_probe_source_height_maps_accept_quality(monkeypatch):
    """httpx 直连 playurl：mock 网络层验证 accept_quality → height 映射。"""
    import asyncio

    import app.core.quality_audit as qa

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            if "web-interface/view" in url:
                return FakeResponse({"code": 0, "data": {"cid": 111}})
            return FakeResponse({
                "code": 0,
                "data": {"accept_quality": [116, 80, 64, 32, 16]},
            })

    monkeypatch.setattr(qa.httpx, "AsyncClient", FakeClient)

    class FakeCredential:
        def get_cookies(self):
            return {"SESSDATA": "x"}

    result = asyncio.run(qa.probe_source_height("BV1aaa1111", credential=FakeCredential()))
    assert result == 1080


def test_probe_source_height_failure_returns_none(monkeypatch):
    import asyncio

    import app.core.quality_audit as qa

    class BoomResponse:
        def raise_for_status(self):
            raise RuntimeError("412 blocked")

        def json(self):
            return {}

    class BoomClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            return BoomResponse()

    monkeypatch.setattr(qa.httpx, "AsyncClient", BoomClient)

    class FakeCredential:
        def get_cookies(self):
            return {}

    assert asyncio.run(qa.probe_source_height("BV1aaa1111", credential=FakeCredential())) is None
    assert asyncio.run(qa.probe_source_height("BV1aaa1111", credential=None)) is None


# ---------- purge 命令与防穿越删除 ----------


def test_purge_command_in_supported_list():
    assert COMMAND_PURGE_LOW_QUALITY in SUPPORTED_COMMANDS


def test_purge_command_payload_validation(tmp_path):
    from app.core.commands import validate_command_payload

    ok = validate_command_payload(
        COMMAND_PURGE_LOW_QUALITY, {"asset_ids": ["BV1aaa1111", "BV1bbb2222"]}
    )
    assert ok == {"asset_ids": ["BV1aaa1111", "BV1bbb2222"]}
    with pytest.raises(Exception, match="非空"):
        validate_command_payload(COMMAND_PURGE_LOW_QUALITY, {"asset_ids": []})
    with pytest.raises(Exception, match="最多"):
        validate_command_payload(
            COMMAND_PURGE_LOW_QUALITY, {"asset_ids": ["BV1aaa1111"] * 1001}
        )
    from app.core.commands import CommandError

    with pytest.raises(CommandError):
        validate_command_payload(COMMAND_PURGE_LOW_QUALITY, {"asset_ids": ["../evil111"]})


class PurgeDbStub:
    def __init__(self, paths):
        self.paths = paths
        self.deleted = []

    def get_asset_path(self, bvid):
        return self.paths.get(bvid)

    def delete_asset(self, bvid):
        self.deleted.append(bvid)
        return True


class PurgePathMgr:
    def __init__(self, root):
        self.root = root


class PurgeScanner:
    def __init__(self, db, root, config_path=None):
        self.db = db
        self.path_mgr = PurgePathMgr(root)
        self.config_path = config_path
        self._forced_redownloads = set()

    def purge_low_quality_assets(self, asset_ids):
        from app.scheduler.scanner import FavScanner

        return FavScanner.purge_low_quality_assets(self, asset_ids)


def test_purge_deletes_inside_root_and_registers_redownload(tmp_path):
    root = tmp_path / "downloads"
    asset_dir = root / "视频A [BV1aaa1111]"
    asset_dir.mkdir(parents=True)
    (asset_dir / "x.mp4").write_text("data", encoding="utf-8")
    db = PurgeDbStub({"BV1aaa1111": str(asset_dir)})
    scanner = PurgeScanner(db, root)

    purged, failed = scanner.purge_low_quality_assets(["BV1aaa1111"])
    assert (purged, failed) == (1, 0)
    assert not asset_dir.exists()
    assert db.deleted == ["BV1aaa1111"]
    assert "BV1aaa1111" in scanner._forced_redownloads


def test_purge_rejects_outside_root(tmp_path):
    outside = tmp_path / "elsewhere" / "视频B [BV1bbb]"
    outside.mkdir(parents=True)
    db = PurgeDbStub({"BV1bbb2222": str(outside)})
    scanner = PurgeScanner(db, tmp_path / "downloads")

    purged, failed = scanner.purge_low_quality_assets(["BV1bbb2222"])
    assert (purged, failed) == (0, 1)
    assert outside.exists()  # 未被删除
    assert db.deleted == []


def test_purge_rejects_name_mismatch(tmp_path):
    root = tmp_path / "downloads"
    other_dir = root / "别的目录"
    other_dir.mkdir(parents=True)
    db = PurgeDbStub({"BV1ccc3333": str(other_dir)})
    scanner = PurgeScanner(db, root)

    purged, failed = scanner.purge_low_quality_assets(["BV1ccc3333"])
    assert (purged, failed) == (0, 1)
    assert other_dir.exists()


def test_purge_missing_db_record(tmp_path):
    db = PurgeDbStub({})
    scanner = PurgeScanner(db, tmp_path / "downloads")
    purged, failed = scanner.purge_low_quality_assets(["BV1ddd4444"])
    assert (purged, failed) == (0, 1)


def test_dispatch_purge_command(tmp_path):
    import asyncio

    channel = CommandChannel(tmp_path / "commands.json")
    record = channel.enqueue(
        COMMAND_PURGE_LOW_QUALITY, {"asset_ids": ["BV1aaa1111"]}
    )

    class PurgeScannerStub:
        def __init__(self):
            self.calls = []

        def purge_low_quality_assets(self, asset_ids):
            self.calls.append(asset_ids)
            return 1, 0

    scanner = PurgeScannerStub()
    asyncio.run(dispatch_commands(channel, scanner, None, None))
    assert scanner.calls == [["BV1aaa1111"]]
    status = channel.command_status(record["id"])
    assert status["status"] == "done"


def test_dispatch_purge_requires_scanner(tmp_path):
    import asyncio

    channel = CommandChannel(tmp_path / "commands.json")
    record = channel.enqueue(COMMAND_PURGE_LOW_QUALITY, {"asset_ids": ["BV1aaa1111"]})
    asyncio.run(dispatch_commands(channel, None, None, None))
    status = channel.command_status(record["id"])
    assert status["status"] == "failed"
    assert "尚未登录" in (status.get("result") or "")


# ---------- 数据库 delete_asset ----------


def test_database_delete_asset(tmp_path):
    manager = DatabaseManager(tmp_path / "a.db")
    manager.update_asset("BV1aaa", "t", "video", 0, "./downloads/x [BV1aaa]", source="fav")
    assert manager.get_asset_path("BV1aaa") == "./downloads/x [BV1aaa]"
    assert manager.delete_asset("BV1aaa") is True
    assert manager.get_asset_path("BV1aaa") is None
    assert manager.delete_asset("BV1aaa") is False
    manager.conn.close()


# ---------- WebUI：下载开关 + 审计键 ----------


def test_download_enabled_key_is_validated_and_immediate():
    from app.webui.queries.settings import (
        CONFIG_SCHEMA,
        effect_for,
        validate_config_payload,
    )

    assert "download_enabled" in CONFIG_SCHEMA["system"]
    assert "quality_audit_enabled" in CONFIG_SCHEMA["system"]
    assert effect_for("system", "download_enabled") == "immediate"
    ok = validate_config_payload(
        {"system": {"download_enabled": True, "quality_audit_enabled": True}}
    )
    assert ok["system"] == {"download_enabled": True, "quality_audit_enabled": True}
    from app.webui.queries.settings import ConfigValidationError

    with pytest.raises(ConfigValidationError, match="布尔"):
        validate_config_payload({"system": {"download_enabled": "yes"}})


# ---------- v1.9.8：免密开关 + 一键审计清除 ----------


def test_disable_auth_key_is_validated_and_immediate():
    from app.webui.queries.settings import (
        CONFIG_SCHEMA,
        effect_for,
        validate_config_payload,
    )

    assert "disable_auth" in CONFIG_SCHEMA["system"]
    assert effect_for("system", "disable_auth") == "immediate"
    ok = validate_config_payload({"system": {"disable_auth": True}})
    assert ok["system"] == {"disable_auth": True}
    with pytest.raises(Exception, match="布尔"):
        validate_config_payload({"system": {"disable_auth": "off"}})


def test_purge_command_allows_1000_assets():
    from app.core.commands import validate_command_payload

    ok = validate_command_payload(
        COMMAND_PURGE_LOW_QUALITY, {"asset_ids": ["BV1aaa1111"] * 1000}
    )
    assert len(ok["asset_ids"]) == 1000
    with pytest.raises(Exception, match="最多"):
        validate_command_payload(
            COMMAND_PURGE_LOW_QUALITY, {"asset_ids": ["BV1aaa1111"] * 1001}
        )


def test_health_reports_auth_disabled(tmp_path):

    config_path = tmp_path / "config.yaml"
    base = {
        "system": {
            "download_path": str(tmp_path / "downloads"),
            "db_path": str(tmp_path / "archive.db"),
            "cookie_path": str(tmp_path / "cookie.json"),
            "disable_auth": True,
        },
        "network": {},
        "components": {
            "yt-dlp": {"strategy": "auto", "path": "./bin/yt-dlp"},
            "ffmpeg": {"strategy": "auto", "path": "./bin/ffmpeg"},
        },
    }
    config_path.write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
    (tmp_path / "downloads").mkdir()
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>app</html>", encoding="utf-8")
    import sqlite3

    with sqlite3.connect(tmp_path / "archive.db") as connection:
        connection.execute(
            "CREATE TABLE assets (bvid TEXT PRIMARY KEY, title TEXT, type TEXT, "
            "status INTEGER, path TEXT, last_check TEXT, p_count INTEGER)"
        )
    app = create_app(
        project_root=tmp_path,
        config_path=config_path,
        db_path=tmp_path / "archive.db",
        static_dir=static_dir,
        host="0.0.0.0",
        token="some-token",
    )
    client = TestClient(app)
    body = client.get("/api/health").json()
    assert body["auth_disabled"] is True
    # 免密生效：无凭据直接访问受保护端点
    assert client.get("/api/dashboard").status_code == 200


def test_auth_required_when_disable_auth_false(tmp_path):
    config_path = tmp_path / "config.yaml"
    base = {
        "system": {
            "download_path": str(tmp_path / "downloads"),
            "db_path": str(tmp_path / "archive.db"),
            "cookie_path": str(tmp_path / "cookie.json"),
            "disable_auth": False,
        },
        "network": {},
        "components": {
            "yt-dlp": {"strategy": "auto", "path": "./bin/yt-dlp"},
            "ffmpeg": {"strategy": "auto", "path": "./bin/ffmpeg"},
        },
    }
    config_path.write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
    (tmp_path / "downloads").mkdir()
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>app</html>", encoding="utf-8")
    app = create_app(
        project_root=tmp_path,
        config_path=config_path,
        db_path=tmp_path / "archive.db",
        static_dir=static_dir,
        host="0.0.0.0",
        token="t0ken-xyz",
    )
    client = TestClient(app)
    body = client.get("/api/health").json()
    assert body["auth_disabled"] is False
    assert client.get("/api/dashboard").status_code == 401
