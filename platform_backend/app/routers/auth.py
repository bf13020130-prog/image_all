from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
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


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
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
