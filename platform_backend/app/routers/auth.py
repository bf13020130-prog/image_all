from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..auth import (
    authenticate,
    change_password,
    clear_session,
    create_session,
    public_user,
    require_active_user,
    require_csrf_user,
    resolve_auth_client,
    session_token_from_request,
)
from ..database import new_id, transaction
from ..config import CONFIG
from ..security import hash_password, utc_now


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class PasswordChangeRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    user = authenticate(payload.username, payload.password)
    session = create_session(response, user["id"], client=resolve_auth_client(request))
    return {
        "user": public_user(user),
        "csrf_token": session["csrf_token"],
    }


@router.post("/register")
def register(payload: RegisterRequest, request: Request, response: Response) -> dict:
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="账号不能为空。")

    now = utc_now()
    user_id = new_id("usr")
    try:
        password_hash = hash_password(payload.password, min_length=1)
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO users (
                  id, username, display_name, password_hash, role, status,
                  must_change_password, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'user', 'active', 0, ?, ?)
                """,
                (user_id, username, username, password_hash, now, now),
            )
            conn.execute(
                """
                INSERT INTO user_quotas (
                  user_id, balance, daily_limit, monthly_limit, concurrent_limit,
                  storage_limit_mb, created_at, updated_at
                )
                VALUES (?, 0, 0, 0, ?, 10240, ?, ?)
                """,
                (user_id, CONFIG.default_user_concurrent_limit, now, now),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="账号已存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user = authenticate(username, payload.password)
    session = create_session(response, user_id, client=resolve_auth_client(request))
    return {
        "user": public_user(user),
        "csrf_token": session["csrf_token"],
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: dict = Depends(require_csrf_user),
) -> dict:
    client = resolve_auth_client(request)
    token = getattr(request.state, "session_token", None) or session_token_from_request(request, client)
    clear_session(response, token, client=client)
    return {"status": "ok"}


@router.get("/me")
def me(user: dict = Depends(require_active_user)) -> dict:
    return {
        "user": public_user(user),
        "csrf_token": user["csrf_token"],
    }


@router.post("/password")
def update_password(
    payload: PasswordChangeRequest,
    user: dict = Depends(require_csrf_user),
) -> dict:
    change_password(user["id"], payload.old_password, payload.new_password)
    return {"status": "ok"}
