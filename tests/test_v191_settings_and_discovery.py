"""v1.9.1 settings schema and discovery-service coverage.

Targets the validation branches added with the full settings page
(followings / wordcloud / summary, component paths, github proxy) and the
WebUI-side bilibili discovery facade.
"""

import pytest
import yaml
from fastapi.testclient import TestClient

from app.webui import create_app
from app.webui.queries.settings import (
    ConfigValidationError,
    public_config,
    validate_config_payload,
)


# ---------- followings ----------


def test_followings_accepts_full_section():
    payload = {
        "mode": "list",
        "article_types": "article",
        "list": [{"mid": 946974, "name": "某UP主"}],
    }
    assert validate_config_payload({"followings": payload})["followings"] == payload


def test_followings_normalizes_comment_emptied_list():
    # YAML 全注释的 list 解析为 None；按空列表处理。
    assert validate_config_payload({"followings": {"mode": "off", "list": None}})[
        "followings"
    ] == {"mode": "off", "list": []}


def test_followings_rejects_unknown_mode_and_fields():
    with pytest.raises(ConfigValidationError, match="mode"):
        validate_config_payload({"followings": {"mode": "everything"}})
    with pytest.raises(ConfigValidationError, match="不允许"):
        validate_config_payload({"followings": {"hacks": 1}})
    with pytest.raises(ConfigValidationError, match="article_types"):
        validate_config_payload({"followings": {"article_types": "videos"}})
    with pytest.raises(ConfigValidationError, match="mid"):
        validate_config_payload({"followings": {"list": [{"mid": -1, "name": "x"}]}})


# ---------- wordcloud / summary ----------


def test_wordcloud_and_summary_validation():
    ok = validate_config_payload(
        {"wordcloud": {"enabled": True, "max_terms": 60}, "summary": {"enabled": False, "mode": "local", "max_chars": 220}}
    )
    assert ok["wordcloud"] == {"enabled": True, "max_terms": 60}
    assert ok["summary"]["mode"] == "local"
    with pytest.raises(ConfigValidationError):
        validate_config_payload({"wordcloud": {"max_terms": 0}})
    with pytest.raises(ConfigValidationError):
        validate_config_payload({"summary": {"mode": "gpt"}})
    with pytest.raises(ConfigValidationError):
        validate_config_payload({"summary": {"max_chars": 10}})
    with pytest.raises(ConfigValidationError, match="不允许"):
        validate_config_payload({"wordcloud": {"font": "x"}})


# ---------- component paths & github proxy ----------


def test_component_path_and_proxy_validation():
    ok = validate_config_payload(
        {
            "components": {
                "yt-dlp": {"strategy": "auto", "path": "C:/bin/yt-dlp.exe"},
                "ffmpeg": {"strategy": "off", "path": None},
            },
            "network": {"github_proxy_url": "  https://mirror.invalid/  "},
        }
    )
    assert ok["components"]["yt-dlp"]["path"] == "C:/bin/yt-dlp.exe"
    assert ok["components"]["ffmpeg"]["path"] == ""
    assert ok["network"]["github_proxy_url"] == "https://mirror.invalid/"
    with pytest.raises(ConfigValidationError):
        validate_config_payload({"components": {"yt-dlp": {"strategy": "auto", "path": "a\nb"}}})
    with pytest.raises(ConfigValidationError):
        validate_config_payload({"network": {"github_proxy_url": "a" * 300}})


def test_new_boolean_and_integrity_keys_validation():
    ok = validate_config_payload(
        {
            "system": {
                "sync_watch_history": True,
                "db_wal": False,
                "check_update_on_start": True,
                "max_history_days": 180,
                "verify_integrity": "full",
            }
        }
    )
    assert ok["system"]["verify_integrity"] == "full"
    with pytest.raises(ConfigValidationError):
        validate_config_payload({"system": {"verify_integrity": "paranoid"}})
    with pytest.raises(ConfigValidationError):
        validate_config_payload({"system": {"db_wal": "yes"}})
    with pytest.raises(ConfigValidationError):
        validate_config_payload({"system": {"max_history_days": -1}})


def test_public_config_passes_through_new_sections():
    raw = {
        "followings": {"mode": "off", "article_types": "off", "list": None},
        "wordcloud": {"enabled": False, "max_terms": 60},
        "summary": {"enabled": False, "mode": "local", "max_chars": 220},
        "components": {
            "yt-dlp": {"strategy": "auto", "path": "./bin/yt-dlp"},
            "ffmpeg": {"strategy": "notify", "path": "./bin/ffmpeg"},
        },
    }
    result = public_config(raw)
    assert result["followings"] == {"mode": "off", "article_types": "off", "list": []}
    assert result["components"]["yt-dlp"] == {"strategy": "auto", "path": "./bin/yt-dlp"}


# ---------- discovery facade (503 paths, real endpoints) ----------


@pytest.fixture
def discover_fixture(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = {
        "system": {
            "download_path": str(tmp_path / "downloads"),
            "db_path": str(tmp_path / "archive.db"),
            # cookie 指向不存在的文件 → check_cookie 返回 (None, None)
            "cookie_path": str(tmp_path / "missing-cookie.json"),
        },
        "network": {},
        "components": {
            "yt-dlp": {"strategy": "auto", "path": "./bin/yt-dlp"},
            "ffmpeg": {"strategy": "auto", "path": "./bin/ffmpeg"},
        },
    }
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
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
        token="disc-token",
    )
    return TestClient(app)


def test_discover_favorites_without_cookie_returns_503(discover_fixture):
    client = discover_fixture
    login = client.post("/api/auth/login", json={"token": "disc-token"})
    headers = {"Authorization": f"Bearer {login.json()['session']}"}
    response = client.get("/api/discover/favorites", headers=headers)
    assert response.status_code == 503
    assert "登录凭据" in response.json()["detail"]


def test_discover_collections_without_cookie_returns_503(discover_fixture):
    client = discover_fixture
    login = client.post("/api/auth/login", json={"token": "disc-token"})
    headers = {"Authorization": f"Bearer {login.json()['session']}"}
    response = client.get("/api/discover/collections", headers=headers)
    assert response.status_code == 503


def test_discover_endpoints_require_authentication(discover_fixture):
    client = discover_fixture
    assert client.get("/api/discover/favorites").status_code == 401
    assert client.get("/api/discover/collections").status_code == 401


# ---------- auth store edge cases ----------


def test_auth_store_session_ttl_and_prune(tmp_path, monkeypatch):
    from app.webui.auth_store import AuthStore

    path = tmp_path / "auth.json"
    store = AuthStore(path)
    session = store.issue_session()
    assert store.session_is_valid(session)
    # 把会话时间拨回 TTL 之外
    import time

    key = store._session_key(session)
    store._sessions[key]["created"] = time.time() - (8 * 24 * 3600)
    assert not store.session_is_valid(session)
    # 过期会话在下次保存时被清理
    store.issue_session()
    assert key not in store._sessions


def test_bootstrap_password_hidden_after_change(tmp_path):
    from app.webui.auth_store import AuthStore

    path = tmp_path / "auth.json"
    store = AuthStore(path)
    initial = store.bootstrap_password()
    assert initial
    store.change_password(initial, "N3w!Pass1")
    assert store.bootstrap_password() is None
    assert "initial_password" not in path.read_text(encoding="utf-8")
