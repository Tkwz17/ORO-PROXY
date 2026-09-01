import os
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

os.environ["OROPROXY_DB_PATH"] = str(Path(__file__).parent / "test.db")
os.environ["OROPROXY_SETUP_CODE_FILE"] = str(Path(__file__).parent / "setup_code.txt")
os.environ["OROPROXY_SECRET_FILE"] = str(Path(__file__).parent / "session_secret.txt")
os.environ["OROPROXY_AUTH_SCRIPT"] = "/bin/true"
os.environ["OROPROXY_WIFI_CONFIG_FILE"] = str(Path(__file__).parent / "home_wifi.json")
os.environ["OROPROXY_NETWORK_STATE_FILE"] = str(Path(__file__).parent / "network_state.json")
os.environ["OROPROXY_AP_MODE_MANAGER_SCRIPT"] = "/bin/true"

import app  # noqa: E402


def setup_module(_):
    for p in ["test.db", "setup_code.txt", "session_secret.txt", "home_wifi.json", "network_state.json"]:
        f = Path(__file__).parent / p
        if f.exists():
            f.unlink()
    app.init_db()
    app.session_secret()
    app.first_boot_setup_code()


def teardown_module(_):
    for p in ["test.db", "setup_code.txt", "session_secret.txt", "home_wifi.json", "network_state.json"]:
        f = Path(__file__).parent / p
        if f.exists():
            f.unlink()


def test_setup_flow():
    client = TestClient(app.app)
    status = client.get("/api/setup/status")
    assert status.status_code == 200
    assert status.json()["setup_complete"] is False

    code = Path(os.environ["OROPROXY_SETUP_CODE_FILE"]).read_text(encoding="utf-8").strip()
    done = client.post("/api/setup/complete", json={"setup_code": code, "password": "verysecurepass123"})
    assert done.status_code == 200

    login = client.post("/api/admin/login", json={"password": "verysecurepass123"})
    assert login.status_code == 200
    assert "token" in login.json()


def _admin_headers(client: TestClient):
    login = client.post("/api/admin/login", json={"password": "verysecurepass123"})
    assert login.status_code == 200
    return {"Authorization": "Token " + login.json()["token"]}


def test_user_admin_crud():
    client = TestClient(app.app)
    headers = _admin_headers(client)
    create = client.post(
        "/api/users",
        json={"username": "alice", "password": "password123", "daily_minutes": 60},
        headers=headers,
    )
    assert create.status_code == 200

    update = client.put("/api/users/alice", json={"daily_minutes": 90, "is_active": True}, headers=headers)
    assert update.status_code == 200

    users = client.get("/api/users", headers=headers)
    assert users.status_code == 200
    user = [u for u in users.json() if u["username"] == "alice"][0]
    assert user["daily_minutes"] == 90
    assert user["is_active"] is True

    delete = client.delete("/api/users/alice", headers=headers)
    assert delete.status_code == 204


def test_user_admin_rejects_invalid_field_types():
    client = TestClient(app.app)
    headers = _admin_headers(client)

    invalid_minutes = client.post(
        "/api/users",
        json={"username": "eve", "password": "password123", "daily_minutes": "not-a-number"},
        headers=headers,
    )
    assert invalid_minutes.status_code == 400

    create = client.post(
        "/api/users",
        json={"username": "eve", "password": "password123", "daily_minutes": 60},
        headers=headers,
    )
    assert create.status_code == 200

    invalid_active = client.put("/api/users/eve", json={"is_active": "false"}, headers=headers)
    assert invalid_active.status_code == 400


def test_revoke_session():
    client = TestClient(app.app)
    headers = _admin_headers(client)
    client.post("/api/users", json={"username": "bob", "password": "password123", "daily_minutes": 30}, headers=headers)

    def fake_quota_request(method, path, payload=None):
        if method == "POST" and path in ("/v1/sessions/start", "/v1/sessions/stop"):
            return SimpleNamespace(status_code=200, json=lambda: {})
        if method == "GET" and path == "/v1/sessions/active":
            return SimpleNamespace(status_code=200, json=lambda: [])
        return SimpleNamespace(status_code=404, json=lambda: {})

    app.quota_request = fake_quota_request
    app.update_auth_set = lambda *_args, **_kwargs: None

    login = client.post("/api/auth/login", json={"username": "bob", "password": "password123", "client_mac": "aa:bb:cc:dd:ee:ff"})
    assert login.status_code == 200
    sid = login.json()["session_id"]

    revoke = client.post(
        "/api/sessions/revoke",
        json={"session_id": sid, "client_mac": "aa:bb:cc:dd:ee:ff", "username": "bob"},
        headers=headers,
    )
    assert revoke.status_code == 200


def test_network_connect_flow():
    client = TestClient(app.app)

    state = client.get("/api/network/state")
    assert state.status_code == 200
    assert state.json()["mode"] == "ap"

    invalid = client.post("/api/network/connect", json={"ssid": "", "password": "secret1234"})
    assert invalid.status_code == 400

    connect = client.post("/api/network/connect", json={"ssid": "HomeNet", "password": "secret1234"})
    assert connect.status_code == 200
    assert connect.json()["ok"] is True

    creds = Path(os.environ["OROPROXY_WIFI_CONFIG_FILE"]).read_text(encoding="utf-8")
    assert "\"ssid\": \"HomeNet\"" in creds
    assert "\"psk\": \"secret1234\"" in creds

    app.write_network_state("home", connected_ssid="HomeNet")
    blocked = client.post("/api/network/connect", json={"ssid": "OtherNet", "password": "secret1234"})
    assert blocked.status_code == 409
