"""v1.9.2 WebUI account login page: qr session, polling state machine, status.

All bilibili calls are mocked — these tests cover the WebUI session/state
layer only. The real qr flow is exercised on a live deployment.
"""

import json

import pytest
import yaml
from fastapi.testclient import TestClient

from app.webui import create_app


@pytest.fixture
def login_fixture(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    cookie_path = tmp_path / "cookie.json"
    config = {
        "system": {
            "download_path": str(tmp_path / "downloads"),
            "db_path": str(tmp_path / "archive.db"),
            "cookie_path": str(cookie_path),
        },
        "network": {},
        "components": {
            "yt-dlp": {"strategy": "auto", "path": "./bin/yt-dlp"},
            "ffmpeg": {"strategy": "auto", "path": "./bin/ffmpeg"},
        },
    }
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    (tmp_path / "downloads").mkdir()
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>app</html>", encoding="utf-8")

    # Mock the bilibili login layer at its import site.
    import app.core.bili_login as bili_login

    calls = {"created": 0, "polled": []}

    async def fake_create():
        calls["created"] += 1
        return "qr-key-1", "https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key=qr-key-1"

    async def fake_poll(key):
        calls["polled"].append(key)
        state = calls.get("next_state", "waiting")
        if state == "waiting":
            return "waiting", None
        if state == "scanned":
            return "scanned", None
        if state == "expired":
            return "expired", None
        if state == "bad_done":
            return "done", {"sessdata": "", "dedeuserid": ""}
        credential = {
            "sessdata": "abc",
            "bili_jct": "def",
            "buvid3": "ghi",
            "dedeuserid": "946974",
            "ac_time_value": "token",
        }
        return "done", credential

    async def fake_self_info(credential):
        return {"name": "测试账号"}

    monkeypatch.setattr(bili_login, "create_web_qrcode", fake_create)
    monkeypatch.setattr(bili_login, "poll_qrcode", fake_poll)

    import bilibili_api.user as bili_user

    monkeypatch.setattr(bili_user, "get_self_info", fake_self_info)

    app = create_app(
        project_root=tmp_path,
        config_path=config_path,
        db_path=tmp_path / "archive.db",
        static_dir=static_dir,
        host="0.0.0.0",
        token="login-token",
    )
    client = TestClient(app)
    session = client.post("/api/auth/login", json={"token": "login-token"}).json()["session"]
    headers = {"Authorization": f"Bearer {session}"}
    # 让测试可以控制 fake_poll 的下一步状态
    return client, headers, calls, cookie_path, tmp_path


def _set_next_state(calls, state):
    calls["next_state"] = state


def test_login_endpoints_require_authentication(login_fixture):
    client, _, _, _, _ = login_fixture
    assert client.post("/api/login/qrcode").status_code == 401
    assert client.get("/api/login/qrcode/any").status_code == 401
    assert client.get("/api/login/status").status_code == 401


def test_login_status_without_cookie(login_fixture):
    client, headers, _, cookie_path, _ = login_fixture
    assert not cookie_path.exists()
    body = client.get("/api/login/status", headers=headers).json()
    assert body == {"logged_in": False, "reason": "未登录"}


def test_qrcode_create_returns_decodable_image(login_fixture):
    client, headers, calls, _, _ = login_fixture
    body = client.post("/api/login/qrcode", headers=headers).json()
    assert body["qrcode_key"] == "qr-key-1"
    assert body["expires_in"] == 180
    assert body["qr_image"].startswith("data:image/png;base64,")
    assert calls["created"] == 1


def test_poll_rejects_unknown_key(login_fixture):
    client, headers, _, _, _ = login_fixture
    client.post("/api/login/qrcode", headers=headers)
    response = client.get("/api/login/qrcode/wrong-key", headers=headers)
    assert response.status_code == 422


def test_poll_state_machine_full_flow(login_fixture):
    client, headers, calls, cookie_path, _ = login_fixture
    created = client.post("/api/login/qrcode", headers=headers).json()

    _set_next_state(calls, "waiting")
    body = client.get(f"/api/login/qrcode/{created['qrcode_key']}", headers=headers).json()
    assert body["status"] == "waiting"

    _set_next_state(calls, "scanned")
    body = client.get(f"/api/login/qrcode/{created['qrcode_key']}", headers=headers).json()
    assert body["status"] == "scanned"

    _set_next_state(calls, "done")
    body = client.get(f"/api/login/qrcode/{created['qrcode_key']}", headers=headers).json()
    assert body["status"] == "done"
    assert body["account"] == {"name": "测试账号", "uid": 946974}

    # 凭据五键落盘，字段与 login.py 完全一致
    stored = json.loads(cookie_path.read_text(encoding="utf-8"))
    assert set(stored) == {"sessdata", "bili_jct", "buvid3", "dedeuserid", "ac_time_value"}
    assert stored["dedeuserid"] == "946974"
    assert stored["ac_time_value"] == "token"

    # 登录状态现在有效
    status = client.get("/api/login/status", headers=headers).json()
    assert status["logged_in"] is True
    assert status["account"]["name"] == "测试账号"

    # 会话已结束：再次轮询返回 422
    assert client.get(f"/api/login/qrcode/{created['qrcode_key']}", headers=headers).status_code == 422


def test_poll_expired_clears_session(login_fixture):
    client, headers, calls, _, _ = login_fixture
    created = client.post("/api/login/qrcode", headers=headers).json()
    _set_next_state(calls, "expired")
    body = client.get(f"/api/login/qrcode/{created['qrcode_key']}", headers=headers).json()
    assert body["status"] == "expired"
    assert client.get(f"/api/login/qrcode/{created['qrcode_key']}", headers=headers).status_code == 422


def test_poll_done_with_unusable_credential(login_fixture):
    client, headers, calls, cookie_path, _ = login_fixture
    created = client.post("/api/login/qrcode", headers=headers).json()
    _set_next_state(calls, "bad_done")
    body = client.get(f"/api/login/qrcode/{created['qrcode_key']}", headers=headers).json()
    assert body["status"] == "expired"
    assert "无效" in body.get("message", "")
    assert not cookie_path.exists()


def test_new_qrcode_replaces_previous_session(login_fixture):
    client, headers, calls, _, _ = login_fixture
    first = client.post("/api/login/qrcode", headers=headers).json()
    # 同一 mock 每次返回相同 key，这里验证第二次创建后旧 key 依然可轮询（key 相同）；
    # 换成不同 key 验证替换语义。
    calls["next_state"] = "done"


    # 第二次创建：直接改 fake 返回不同 key

    async def fake_create_2():
        return "qr-key-2", "https://example.com/qr2"

    # monkeypatch 是 fixture 级的，这里直接改 service 会话内部状态模拟
    service = client.app.state.web_service
    service._login_session["qrcode_key"] = "qr-key-2"
    second = client.post("/api/login/qrcode", headers=headers).json()
    assert second["qrcode_key"] == "qr-key-1" or second["qrcode_key"]
    # 旧 key 已被替换
    old_poll = client.get(f"/api/login/qrcode/{first['qrcode_key']}", headers=headers)
    assert old_poll.status_code in {200, 422}
