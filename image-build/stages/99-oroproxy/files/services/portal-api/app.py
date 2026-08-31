import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

DB_PATH = Path(os.getenv("OROPROXY_DB_PATH", "/var/lib/oroproxy/oroproxy.db"))
SETUP_CODE_FILE = Path(os.getenv("OROPROXY_SETUP_CODE_FILE", "/etc/oroproxy/setup_code"))
SECRET_FILE = Path(os.getenv("OROPROXY_SECRET_FILE", "/etc/oroproxy/session_secret"))
QUOTA_URL = os.getenv("OROPROXY_QUOTA_URL", "http://127.0.0.1:9090")
AUTH_SCRIPT = os.getenv("OROPROXY_AUTH_SCRIPT", "/opt/oroproxy/services/ap-manager/manage_auth_set.sh")

app = FastAPI(title="OroProxy Portal API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def db_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS admin (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              password_hash TEXT,
              setup_complete INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT
            );
            INSERT OR IGNORE INTO admin(id, password_hash, setup_complete, updated_at)
            VALUES (1, NULL, 0, CURRENT_TIMESTAMP);

            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT UNIQUE NOT NULL,
              password_hash TEXT NOT NULL,
              daily_minutes INTEGER NOT NULL CHECK (daily_minutes > 0),
              is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY,
              username TEXT NOT NULL,
              client_mac TEXT NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO settings(key, value) VALUES ('hostname_logging_enabled', 'false');
            """
        )


def session_secret() -> bytes:
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32), encoding="utf-8")
        SECRET_FILE.chmod(0o600)
    return SECRET_FILE.read_text(encoding="utf-8").strip().encode("utf-8")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return f"{salt}${digest}"


def verify_password(password: str, value: str) -> bool:
    salt, digest = value.split("$", 1)
    return hmac.compare_digest(hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest(), digest)


def sign_token(payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(session_secret(), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + b"." + sig).decode("utf-8")


def parse_token(token: str) -> Optional[dict]:
    try:
        raw = base64.urlsafe_b64decode(token.encode("utf-8"))
        body, sig = raw.rsplit(b".", 1)
        expected = hmac.new(session_secret(), body, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(body.decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def require_admin(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "").strip()
    token = auth_header.replace("Bearer ", "").replace("Token ", "").strip()
    payload = parse_token(token)
    if not payload or payload.get("kind") != "admin":
        raise HTTPException(status_code=401, detail="admin auth required")
    return payload["sub"]


def require_setup_complete() -> None:
    with db_conn() as conn:
        row = conn.execute("SELECT setup_complete FROM admin WHERE id = 1").fetchone()
    if not row or row["setup_complete"] != 1:
        raise HTTPException(status_code=423, detail="setup incomplete")


def first_boot_setup_code() -> str:
    if SETUP_CODE_FILE.exists():
        return SETUP_CODE_FILE.read_text(encoding="utf-8").strip()
    SETUP_CODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    code = secrets.token_hex(4)
    SETUP_CODE_FILE.write_text(code, encoding="utf-8")
    SETUP_CODE_FILE.chmod(0o600)
    return code


def validate_mac(mac: str) -> str:
    mac = mac.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac):
        raise HTTPException(status_code=400, detail="invalid client_mac")
    return mac


def update_auth_set(action: str, mac: str) -> None:
    subprocess.run([AUTH_SCRIPT, action, mac], check=False)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    session_secret()
    first_boot_setup_code()


@app.get("/api/setup/status")
def setup_status():
    with db_conn() as conn:
        row = conn.execute("SELECT setup_complete FROM admin WHERE id = 1").fetchone()
    return {"setup_complete": bool(row and row["setup_complete"] == 1)}


@app.post("/api/setup/complete")
def setup_complete(payload: dict):
    if payload.get("setup_code") != first_boot_setup_code():
        raise HTTPException(status_code=403, detail="invalid setup code")
    password = payload.get("password", "")
    if len(password) < 12:
        raise HTTPException(status_code=400, detail="password must be at least 12 characters")
    with db_conn() as conn:
        conn.execute(
            "UPDATE admin SET password_hash = ?, setup_complete = 1, updated_at = ? WHERE id = 1",
            (hash_password(password), datetime.now(UTC).isoformat()),
        )
    return {"ok": True}


@app.post("/api/admin/login")
def admin_login(payload: dict):
    with db_conn() as conn:
        row = conn.execute("SELECT password_hash, setup_complete FROM admin WHERE id = 1").fetchone()
    if not row or row["setup_complete"] != 1 or not row["password_hash"]:
        raise HTTPException(status_code=423, detail="setup incomplete")
    if not verify_password(payload.get("password", ""), row["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = sign_token({"kind": "admin", "sub": "admin", "exp": int(time.time()) + 8 * 3600})
    return {"token": token}


@app.post("/api/users")
def create_user(payload: dict, _: str = Depends(require_admin)):
    require_setup_complete()
    username = payload.get("username", "").strip()
    password = payload.get("password", "")
    daily_minutes = int(payload.get("daily_minutes", 0))
    if not username or len(password) < 8 or daily_minutes <= 0:
        raise HTTPException(status_code=400, detail="invalid user payload")
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO users(username, password_hash, daily_minutes) VALUES(?, ?, ?)",
            (username, hash_password(password), daily_minutes),
        )
    return {"ok": True}


@app.get("/api/users")
def list_users(_: str = Depends(require_admin)):
    require_setup_complete()
    with db_conn() as conn:
        rows = conn.execute("SELECT username, daily_minutes, is_active FROM users ORDER BY username").fetchall()
    return [{"username": r["username"], "daily_minutes": r["daily_minutes"], "is_active": bool(r["is_active"])} for r in rows]


@app.delete("/api/users/{username}")
def delete_user(username: str, _: str = Depends(require_admin)):
    require_setup_complete()
    with db_conn() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
    return JSONResponse(status_code=204, content={})


@app.post("/api/auth/login")
def user_login(payload: dict):
    require_setup_complete()
    username = payload.get("username", "").strip()
    password = payload.get("password", "")
    client_mac = validate_mac(payload.get("client_mac", ""))
    if not username or not client_mac:
        raise HTTPException(status_code=400, detail="missing credentials")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT password_hash, daily_minutes, is_active FROM users WHERE username = ?", (username,)
        ).fetchone()
    if not row or row["is_active"] != 1 or not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid credentials")

    sid = secrets.token_urlsafe(24)
    exp = int(time.time()) + 24 * 3600
    token = sign_token({"kind": "user", "sub": username, "sid": sid, "mac": client_mac, "exp": exp})

    with db_conn() as conn:
        conn.execute(
            "INSERT INTO sessions(id, username, client_mac, created_at, expires_at) VALUES(?, ?, ?, ?, ?)",
            (sid, username, client_mac, datetime.now(UTC).isoformat(), datetime.fromtimestamp(exp, UTC).isoformat()),
        )

    with httpx.Client(timeout=3.0) as client:
        resp = client.post(
            f"{QUOTA_URL}/v1/sessions/start",
            json={
                "session_id": sid,
                "username": username,
                "client_mac": client_mac,
                "daily_minutes": row["daily_minutes"],
            },
        )
        if resp.status_code >= 300:
            raise HTTPException(status_code=503, detail="quota daemon unavailable")

    update_auth_set("add", client_mac)
    return {"token": token, "session_id": sid, "expires_at": exp}


@app.post("/api/auth/logout")
def user_logout(payload: dict):
    token = payload.get("token", "")
    parsed = parse_token(token)
    if not parsed:
        raise HTTPException(status_code=401, detail="invalid token")

    sid = parsed.get("sid", "")
    mac = validate_mac(parsed.get("mac", ""))

    with db_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))

    with httpx.Client(timeout=3.0) as client:
        client.post(f"{QUOTA_URL}/v1/sessions/stop", json={"session_id": sid})

    update_auth_set("del", mac)
    return {"ok": True}


@app.get("/api/sessions/active")
def active_sessions(_: str = Depends(require_admin)):
    require_setup_complete()
    with httpx.Client(timeout=3.0) as client:
        resp = client.get(f"{QUOTA_URL}/v1/sessions/active")
    if resp.status_code >= 300:
        raise HTTPException(status_code=503, detail="quota daemon unavailable")
    return resp.json()


@app.get("/api/health")
def health(_: str = Depends(require_admin)):
    require_setup_complete()
    st = os.statvfs("/")
    uptime = Path("/proc/uptime").read_text(encoding="utf-8").split()[0]
    with db_conn() as conn:
        logging = conn.execute("SELECT value FROM settings WHERE key='hostname_logging_enabled'").fetchone()["value"]
    return {
        "uptime_seconds": float(uptime),
        "disk_total_bytes": st.f_blocks * st.f_frsize,
        "disk_free_bytes": st.f_bfree * st.f_frsize,
        "hostname_logging_enabled": logging == "true",
    }


@app.post("/api/settings/logging")
def set_logging(payload: dict, _: str = Depends(require_admin)):
    require_setup_complete()
    enabled = bool(payload.get("enabled", False))
    with db_conn() as conn:
        conn.execute("UPDATE settings SET value = ? WHERE key='hostname_logging_enabled'", ("true" if enabled else "false",))
    return {"ok": True, "enabled": enabled}


@app.post("/api/admin/password")
def change_admin_password(payload: dict, _: str = Depends(require_admin)):
    require_setup_complete()
    old_password = payload.get("old_password", "")
    new_password = payload.get("new_password", "")
    if len(new_password) < 12:
        raise HTTPException(status_code=400, detail="new password too short")

    with db_conn() as conn:
        row = conn.execute("SELECT password_hash FROM admin WHERE id = 1").fetchone()
        if not row or not verify_password(old_password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="invalid current password")
        conn.execute(
            "UPDATE admin SET password_hash = ?, updated_at = ? WHERE id = 1",
            (hash_password(new_password), datetime.now(UTC).isoformat()),
        )
    return {"ok": True}
