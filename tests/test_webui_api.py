import json
import sqlite3
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.webui import create_app
from app.webui.service import ConfigValidationError, ReadOnlyDatabase, public_config


@pytest.fixture
def webui_fixture(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = {
        "system": {
            "download_path": str(tmp_path / "downloads"),
            "db_path": str(tmp_path / "archive.db"),
            "cookie_path": str(tmp_path / "private-cookie.json"),
            "min_disk_gb": 5,
            "plex_mode": True,
            "sync_watch_later": False,
            "scan_interval_seconds": 60,
            "max_downloads_per_run": 1,
            "download_timeout_seconds": 120,
        },
        "network": {
            "sync_retry_attempts": 3,
            "sync_retry_backoff_seconds": 2,
            "request_timeout_seconds": 30,
            "github_proxy_url": "https://proxy.invalid/",
        },
        "components": {
            "yt-dlp": {"strategy": "auto", "path": "./bin/yt-dlp"},
            "ffmpeg": {"strategy": "notify", "path": "./bin/ffmpeg"},
        },
        "archive_protection": {
            "mark_deleted_prefix": "[deleted]",
            "tombstone_prefix": "[tombstone]",
        },
        "favorites": [{"id": 10, "name": "收藏夹"}],
        "sync_collections": [{"id": 20, "mid": 30, "name": "合集"}],
    }
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    db_path = tmp_path / "archive.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE assets (bvid TEXT PRIMARY KEY, title TEXT, type TEXT, "
            "status INTEGER, path TEXT, last_check TEXT, p_count INTEGER)"
        )
        connection.executemany(
            "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("BV1", "Video one", "video", 0, "", "2026-08-11T10:00:00", 1),
                ("CV2", "Article two", "article", 1, "", "2026-08-11T09:00:00", 1),
            ],
        )

    (tmp_path / "downloads").mkdir()
    (tmp_path / "runtime.json").write_text(
        json.dumps({"status": "running", "current_asset": "BV1"}), encoding="utf-8"
    )
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>app</html>", encoding="utf-8")
    app = create_app(
        project_root=tmp_path,
        config_path=config_path,
        db_path=db_path,
        static_dir=static_dir,
    )
    return TestClient(app), tmp_path, config_path


def test_health_is_public_and_dashboard_has_read_only_aggregates(webui_fixture):
    client, _, _ = webui_fixture

    assert client.get("/api/health").json() == {
        "status": "ok",
        "auth_required": False,
        "authenticated": True,
    }
    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["version"]
    assert body["runtime"]["status"] == "running"
    assert body["assets"]["total"] == 2
    assert body["assets"]["status_counts"]["0"] == 1
    assert body["recent"][0]["id"] == "BV1"
    assert body["storage"]["exists"] is True


def test_assets_filter_pagination_and_spa_fallback(webui_fixture):
    client, _, _ = webui_fixture

    response = client.get("/api/assets", params={"type": "video", "page_size": 1})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["bvid"] == "BV1"

    fallback = client.get("/dashboard")
    assert fallback.status_code == 200
    assert fallback.text == "<html>app</html>"


def test_poster_is_read_only_and_cannot_escape_download_root(webui_fixture):
    client, root, _ = webui_fixture
    asset_dir = root / "downloads" / "asset"
    asset_dir.mkdir()
    (asset_dir / "poster.jpg").write_bytes(b"poster")
    outside = root / "outside.jpg"
    outside.write_bytes(b"secret")
    with sqlite3.connect(root / "archive.db") as connection:
        connection.execute("UPDATE assets SET path=? WHERE bvid=?", (str(asset_dir), "BV1"))
        connection.commit()

    assert client.get("/api/assets/BV1/poster").content == b"poster"
    listed = client.get("/api/assets", params={"query": "BV1"}).json()["items"][0]
    assert listed["poster_available"] is True
    with sqlite3.connect(root / "archive.db") as connection:
        connection.execute("UPDATE assets SET path=? WHERE bvid=?", (str(root), "BV1"))
        connection.commit()
    assert client.get("/api/assets/BV1/poster").status_code == 404
    listed = client.get("/api/assets", params={"query": "BV1"}).json()["items"][0]
    assert listed["poster_available"] is False


def test_config_redacts_private_fields_and_uses_revision_conflicts(webui_fixture):
    client, _, config_path = webui_fixture
    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert "revision" in body
    assert "db_path" not in json.dumps(body, ensure_ascii=False)
    assert "cookie_path" not in json.dumps(body, ensure_ascii=False)
    assert "github_proxy_url" not in json.dumps(body, ensure_ascii=False)
    assert body["config"]["components"]["yt-dlp"] == {"strategy": "auto"}

    update = {"revision": body["revision"], "config": {"system": {"min_disk_gb": 9}}}
    saved = client.put("/api/config", json=update)
    assert saved.status_code == 200
    local_config = config_path.with_name("config.local.yaml")
    assert yaml.safe_load(local_config.read_text(encoding="utf-8"))["system"]["min_disk_gb"] == 9
    assert client.put("/api/config", json=update).status_code == 409


def test_config_save_preserves_existing_private_local_fields(webui_fixture):
    client, _, config_path = webui_fixture
    local_config = config_path.with_name("config.local.yaml")
    local_config.write_text(
        "system:\n  cookie_path: private-cookie.json\nnetwork:\n  github_proxy_url: https://proxy.invalid/\n",
        encoding="utf-8",
    )
    current = client.get("/api/config").json()

    saved = client.put(
        "/api/config",
        json={
            "revision": current["revision"],
            "config": {"system": {"min_disk_gb": 9}},
        },
    )

    assert saved.status_code == 200
    persisted = yaml.safe_load(local_config.read_text(encoding="utf-8"))
    assert persisted["system"]["cookie_path"] == "private-cookie.json"
    assert persisted["system"]["min_disk_gb"] == 9
    assert persisted["network"]["github_proxy_url"] == "https://proxy.invalid/"


def test_public_config_normalizes_commented_empty_lists():
    assert public_config({"favorites": None, "sync_collections": None}) == {
        "favorites": [],
        "sync_collections": [],
    }


def test_config_rejects_unknown_and_sensitive_fields(webui_fixture):
    client, _, _ = webui_fixture
    revision = client.get("/api/config").json()["revision"]

    response = client.put(
        "/api/config",
        json={"revision": revision, "config": {"system": {"db_path": "leak"}}},
    )
    assert response.status_code == 422


def test_config_rejects_unsafe_numeric_ranges():
    with pytest.raises(ConfigValidationError, match="scan_interval_seconds"):
        public_config({"system": {"scan_interval_seconds": 0}})


def test_non_loopback_requires_token_and_token_protects_api(webui_fixture):
    _, root, config_path = webui_fixture
    with pytest.raises(ValueError):
        create_app(project_root=root, config_path=config_path, host="0.0.0.0")

    app = create_app(
        project_root=root,
        config_path=config_path,
        db_path=root / "archive.db",
        host="0.0.0.0",
        token="test-token",
    )
    client = TestClient(app)
    assert client.get("/api/health").json() == {
        "status": "ok",
        "auth_required": True,
        "authenticated": False,
    }
    assert client.get(
        "/api/health", headers={"Authorization": "Bearer test-token"}
    ).json()["authenticated"] is True
    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/api/assets/BV1/poster").status_code == 401
    assert client.get("/api/unknown").status_code == 401
    assert client.get(
        "/api/dashboard", headers={"Authorization": "Bearer test-token"}
    ).status_code == 200


def test_read_only_database_does_not_create_missing_file(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        ReadOnlyDatabase(path).scalar("SELECT 1")
    assert not path.exists()


def test_assets_reject_unknown_type_filter(webui_fixture):
    client, _, _ = webui_fixture

    response = client.get("/api/assets", params={"type": "unknown"})

    assert response.status_code == 422
