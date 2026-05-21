from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, HTTPException, Request, Response

from .config import CONFIG
from .database import connect, new_id, row_to_dict, transaction
from .security import (
    future_utc,
    hash_password,
    hash_token,
    make_csrf_token,
    make_token,
    utc_now,
    verify_password,
)

AUTH_CLIENTS = {"user", "admin"}


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row.get("display_name", ""),
        "role": row["role"],
        "status": row["status"],
        "must_change_password": bool(row.get("must_change_password")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "last_login_at": row.get("last_login_at"),
    }


def authenticate(username: str, password: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username.strip(),),
        ).fetchone()
    user = row_to_dict(row)
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="账号或密码错误。")
    if user["status"] != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用。")
    return user


def normalize_auth_client(value: str | None) -> str:
    client = str(value or "").strip().lower()
    return client if client in AUTH_CLIENTS else "user"


def resolve_auth_client(request: Request) -> str:
    explicit = request.headers.get("X-Platform-Client") or request.query_params.get("client")
    if explicit:
        return normalize_auth_client(explicit)
    path = request.url.path
    if path.startswith("/api/v1/admin"):
        return "admin"
    return "user"


def session_cookie_name(client: str) -> str:
    return f"{CONFIG.session_cookie_name}_{normalize_auth_client(client)}"


def session_token_from_request(request: Request, client: str | None = None) -> str | None:
    return request.cookies.get(session_cookie_name(client or resolve_auth_client(request)))


def create_session(response: Response, user_id: str, *, client: str = "user") -> dict[str, str]:
    token = make_token()
    csrf_token = make_csrf_token()
    now = utc_now()
    session_id = new_id("ses")
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                id, user_id, token_hash, csrf_token, expires_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user_id,
                hash_token(token),
                csrf_token,
                future_utc(CONFIG.session_days),
                now,
            ),
        )
        conn.execute(
            "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (now, now, user_id),
        )
    response.set_cookie(
        session_cookie_name(client),
        token,
        httponly=True,
        secure=CONFIG.session_cookie_secure,
        samesite="lax",
        max_age=CONFIG.session_days * 24 * 60 * 60,
        path="/",
    )
    response.delete_cookie(CONFIG.session_cookie_name, path="/")
    return {"csrf_token": csrf_token, "session_id": session_id}


def clear_session(response: Response, token: str | None, *, client: str = "user") -> None:
    if token:
        with transaction() as conn:
            conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (utc_now(), hash_token(token)),
            )
    response.delete_cookie(session_cookie_name(client), path="/")
    response.delete_cookie(CONFIG.session_cookie_name, path="/")


def get_current_user(request: Request) -> dict[str, Any]:
    client = resolve_auth_client(request)
    session_token = session_token_from_request(request, client)
    if not session_token:
        raise HTTPException(status_code=401, detail="请先登录。")
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
              users.*,
              sessions.id AS session_id,
              sessions.csrf_token AS csrf_token,
              sessions.expires_at AS session_expires_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ?
              AND sessions.revoked_at IS NULL
              AND sessions.expires_at > ?
            """,
            (hash_token(session_token), utc_now()),
        ).fetchone()
    user = row_to_dict(row)
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录。")
    if user["status"] != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用。")
    request.state.auth_client = client
    request.state.session_token = session_token
    request.state.user = user
    return user


def require_active_user(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return user


def require_csrf_user(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> dict[str, Any]:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return user
    expected = user.get("csrf_token")
    if not expected or not x_csrf_token or x_csrf_token != expected:
        raise HTTPException(status_code=403, detail="CSRF 校验失败。")
    return user


def require_admin(user: dict[str, Any]) -> None:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限。")


def change_password(user_id: str, old_password: str, new_password: str) -> None:
    with connect() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or not verify_password(old_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码不正确。")
    now = utc_now()
    with transaction() as conn:
        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, must_change_password = 0, updated_at = ?
            WHERE id = ?
            """,
            (hash_password(new_password), now, user_id),
        )
