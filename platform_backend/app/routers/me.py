from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import require_active_user, require_csrf_user
from ..settings_service import (
    public_settings_for_user,
    save_user_secrets,
    save_user_settings,
)
from ..storage_service import storage_used_by_user
from ..task_service import get_user_quota


router = APIRouter(prefix="/api/v1/me", tags=["me"])


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


@router.get("/settings")
def get_my_settings(user: dict = Depends(require_active_user)) -> dict:
    return public_settings_for_user(user["id"])


@router.put("/settings")
def update_my_settings(
    payload: SettingsUpdateRequest,
    user: dict = Depends(require_csrf_user),
) -> dict:
    save_user_settings(user["id"], payload.settings)
    save_user_secrets(user["id"], payload.secrets)
    return public_settings_for_user(user["id"])


@router.get("/usage")
def get_my_usage(user: dict = Depends(require_active_user)) -> dict:
    quota = get_user_quota(user["id"])
    return {
        "quota": quota,
        "storage_bytes": storage_used_by_user(user["id"]),
    }
