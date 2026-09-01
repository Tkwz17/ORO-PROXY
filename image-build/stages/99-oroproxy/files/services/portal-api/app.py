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
UPDATE_CHECK_SCRIPT = os.getenv("OROPROXY_UPDATE_CHECK_SCRIPT", "/opt/oroproxy/scripts/update-check.sh")
UPDATE_APPLY_SCRIPT = os.getenv("OROPROXY_UPDATE_APPLY_SCRIPT", "/opt/oroproxy/scripts/apply-update.sh")
UPDATE_STATUS_FILE = Path(os.getenv("OROPROXY_UPDATE_STATUS_FILE", "/var/lib/oroproxy/update-status.json"))

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

            CREATE TABLE IF NOT EXISTS connection_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL,
              client_mac TEXT NOT NULL,
              event TEXT NOT NULL,
              destination_host TEXT,
              created_at TEXT NOT NULL
            );
            """
        )


def session_secret() -> bytes:
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32), encoding="utf-8")
        SECRET_FILE.chmod(0o600)
    return SECRET_FILE.read_text(encoding="utf-8").strip().encode("utf-8")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 310000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, value: str) -> bool:
    try:
        iterations_s, salt_b64, digest_b64 = value.split("$", 2)
        iterations = int(iterations_s)
        salt = base64.b64decode(salt_b64.encode("utf-8"))
        expected = base64.b64decode(digest_b64.encode("utf-8"))
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


def sign_token(payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(session_secret(), body, hashlib.sha256).digest()
    body_b64 = base64.urlsafe_b64encode(body).decode("utf-8").rstrip("=")
    sig_b64 = base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")
    return f"{body_b64}.{sig_b64}"


def parse_token(token: str) -> Optional[dict]:
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = base64.urlsafe_b64decode(body_b64 + "=" * (-len(body_b64) % 4))
        sig = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
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


def quota_request(method: str, path: str, payload: Optional[dict] = None) -> httpx.Response:
    try:
        with httpx.Client(timeout=3.0) as client:
            if method == "GET":
                return client.get(f"{QUOTA_URL}{path}")
            return client.post(f"{QUOTA_URL}{path}", json=payload or {})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="quota daemon unavailable") from exc


def append_connection_log(username: str, client_mac: str, event: str, destination_host: Optional[str] = None) -> None:
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO connection_logs(username, client_mac, event, destination_host, created_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (username, client_mac, event, destination_host, datetime.now(UTC).isoformat()),
        )


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


@app.put("/api/users/{username}")
def update_user(username: str, payload: dict, _: str = Depends(require_admin)):
    require_setup_complete()
    daily_minutes = payload.get("daily_minutes")
    is_active = payload.get("is_active")
    updates = []
    values = []
    if daily_minutes is not None:
        daily_minutes = int(daily_minutes)
        if daily_minutes <= 0:
            raise HTTPException(status_code=400, detail="daily_minutes must be > 0")
        updates.append("daily_minutes = ?")
        values.append(daily_minutes)
    if is_active is not None:
        updates.append("is_active = ?")
        values.append(1 if bool(is_active) else 0)
    if not updates:
        raise HTTPException(status_code=400, detail="no update fields provided")
    values.append(username)
    with db_conn() as conn:
        cur = conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE username = ?", values)
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="user not found")
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
        cur = conn.execute("DELETE FROM users WHERE username = ?", (username,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="user not found")
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

    resp = quota_request(
        "POST",
        "/v1/sessions/start",
        {
            "session_id": sid,
            "username": username,
            "client_mac": client_mac,
            "daily_minutes": row["daily_minutes"],
        },
    )
    if resp.status_code >= 300:
        raise HTTPException(status_code=503, detail="quota daemon unavailable")

    update_auth_set("add", client_mac)
    append_connection_log(username, client_mac, "login")
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

    quota_request("POST", "/v1/sessions/stop", {"session_id": sid})

    update_auth_set("del", mac)
    append_connection_log(parsed.get("sub", "unknown"), mac, "logout")
    return {"ok": True}


@app.get("/api/sessions/active")
def active_sessions(_: str = Depends(require_admin)):
    require_setup_complete()
    resp = quota_request("GET", "/v1/sessions/active")
    if resp.status_code >= 300:
        raise HTTPException(status_code=503, detail="quota daemon unavailable")
    sessions = resp.json()
    out = []
    for session in sessions:
        used = int(session.get("used_seconds", 0))
        total = int(session.get("daily_minutes", 0)) * 60
        session["remaining_seconds"] = max(total - used, 0)
        out.append(session)
    return out


@app.post("/api/sessions/revoke")
def revoke_session(payload: dict, _: str = Depends(require_admin)):
    require_setup_complete()
    session_id = payload.get("session_id", "").strip()
    client_mac = validate_mac(payload.get("client_mac", ""))
    username = payload.get("username", "").strip() or "unknown"
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    with db_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    quota_request("POST", "/v1/sessions/stop", {"session_id": session_id})
    update_auth_set("del", client_mac)
    append_connection_log(username, client_mac, "revoked")
    return {"ok": True}


@app.get("/api/health")
def health(_: str = Depends(require_admin)):
    require_setup_complete()
    st = os.statvfs("/")
    uptime = Path("/proc/uptime").read_text(encoding="utf-8").split()[0]
    with db_conn() as conn:
        logging = conn.execute("SELECT value FROM settings WHERE key='hostname_logging_enabled'").fetchone()["value"]
    connected_clients = 0
    try:
        resp = quota_request("GET", "/v1/sessions/active")
        if resp.status_code < 300:
            connected_clients = len(resp.json())
    except Exception:
        connected_clients = 0
    return {
        "uptime_seconds": float(uptime),
        "disk_total_bytes": st.f_blocks * st.f_frsize,
        "disk_free_bytes": st.f_bfree * st.f_frsize,
        "hostname_logging_enabled": logging == "true",
        "connected_client_count": connected_clients,
    }


@app.post("/api/settings/logging")
def set_logging(payload: dict, _: str = Depends(require_admin)):
    require_setup_complete()
    enabled = bool(payload.get("enabled", False))
    with db_conn() as conn:
        conn.execute("UPDATE settings SET value = ? WHERE key='hostname_logging_enabled'", ("true" if enabled else "false",))
    return {"ok": True, "enabled": enabled}


@app.get("/api/logs")
def list_logs(_: str = Depends(require_admin)):
    require_setup_complete()
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT username, client_mac, event, destination_host, created_at
            FROM connection_logs
            ORDER BY id DESC
            LIMIT 200
            """
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/logs/clear")
def clear_logs(_: str = Depends(require_admin)):
    require_setup_complete()
    with db_conn() as conn:
        conn.execute("DELETE FROM connection_logs")
    return {"ok": True}


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


@app.post("/api/update/check")
def check_updates(_: str = Depends(require_admin)):
    require_setup_complete()
    subprocess.run([UPDATE_CHECK_SCRIPT], check=False)
    return update_status(_)


@app.get("/api/update/status")
def update_status(_: str = Depends(require_admin)):
    require_setup_complete()
    if not UPDATE_STATUS_FILE.exists():
        return {"current": None, "latest": None, "update_available": False}
    try:
        return json.loads(UPDATE_STATUS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"invalid update status: {exc}") from exc


@app.post("/api/update/apply")
def apply_update(_: str = Depends(require_admin)):
    require_setup_complete()
    proc = subprocess.run([UPDATE_APPLY_SCRIPT], check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=f"update failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return {"ok": True, "message": proc.stdout.strip() or "update applied"}
