import os
from pathlib import Path

from fastapi.testclient import TestClient

os.environ["OROPROXY_DB_PATH"] = str(Path(__file__).parent / "test.db")
os.environ["OROPROXY_SETUP_CODE_FILE"] = str(Path(__file__).parent / "setup_code.txt")
os.environ["OROPROXY_SECRET_FILE"] = str(Path(__file__).parent / "session_secret.txt")
os.environ["OROPROXY_AUTH_SCRIPT"] = "/bin/true"

import app  # noqa: E402


def setup_module(_):
    for p in ["test.db", "setup_code.txt", "session_secret.txt"]:
        f = Path(__file__).parent / p
        if f.exists():
            f.unlink()
    app.init_db()
    app.session_secret()
    app.first_boot_setup_code()


def teardown_module(_):
    for p in ["test.db", "setup_code.txt", "session_secret.txt"]:
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
