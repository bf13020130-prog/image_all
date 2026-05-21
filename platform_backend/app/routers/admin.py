from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import public_user, require_admin, require_csrf_user
from ..database import connect, new_id, row_to_dict, transaction
from ..legacy_contract import collect_job_log_entries
from ..security import hash_password, make_temporary_password, utc_now
from ..settings_service import get_admin_global_settings, save_global_settings
from ..storage_service import delete_user_storage, storage_used_by_user
from ..task_service import audit_log, get_job, get_user_quota, list_jobs


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    display_name: str = Field(default="", max_length=120)
    password: str | None = Field(default=None, min_length=8, max_length=200)
    role: str = Field(default="user")
    concurrent_limit: int = Field(default=1, ge=1, le=50)
    storage_limit_mb: int = Field(default=10240, ge=100, le=10_000_000)


class UserPatchRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None)
    status: str | None = Field(default=None)
    concurrent_limit: int | None = Field(default=None, ge=1, le=50)
    storage_limit_mb: int | None = Field(default=None, ge=100, le=10_000_000)
    balance_delta: int | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    balance_reason: str = Field(default="管理员调整", max_length=200)


class GlobalSettingsRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


def _admin(user: dict) -> dict:
    require_admin(user)
    return user


def _validate_role(value: str | None) -> None:
    if value is not None and value not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="角色只能是 admin 或 user。")


def _validate_status(value: str | None) -> None:
    if value is not None and value not in {"active", "disabled"}:
        raise HTTPException(status_code=400, detail="状态只能是 active 或 disabled。")


@router.get("/summary")
def summary(user: dict = Depends(require_csrf_user)) -> dict:
    _admin(user)
    with connect() as conn:
        users = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        disabled = conn.execute(
            "SELECT COUNT(*) AS count FROM users WHERE status = 'disabled'"
        ).fetchone()["count"]
        jobs = conn.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()["count"]
        queued = conn.execute(
            "SELECT COUNT(*) AS count FROM jobs WHERE status IN ('queued', 'running')"
        ).fetchone()["count"]
        storage = conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM job_artifacts"
        ).fetchone()["total"]
    return {
        "users": users,
        "disabled_users": disabled,
        "jobs": jobs,
        "active_jobs": queued,
        "storage_bytes": int(storage or 0),
    }


@router.get("/users")
def list_users(user: dict = Depends(require_csrf_user)) -> dict:
    _admin(user)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    data = []
    for row in rows:
        item = public_user(row_to_dict(row) or {})
        quota = get_user_quota(item["id"])
        item["quota"] = quota
        item["storage_bytes"] = storage_used_by_user(item["id"])
        data.append(item)
    return {"data": data}


@router.post("/users")
def create_user(payload: UserCreateRequest, user: dict = Depends(require_csrf_user)) -> dict:
    _admin(user)
    _validate_role(payload.role)
    temporary_password = payload.password or make_temporary_password()
    now = utc_now()
    user_id = new_id("usr")
    try:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO users (
                  id, username, display_name, password_hash, role, status,
                  must_change_password, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'active', 1, ?, ?)
                """,
                (
                    user_id,
                    payload.username.strip(),
                    payload.display_name.strip() or payload.username.strip(),
                    hash_password(temporary_password),
                    payload.role,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO user_quotas (
                  user_id, balance, daily_limit, monthly_limit, concurrent_limit,
                  storage_limit_mb, created_at, updated_at
                )
                VALUES (?, 0, 0, 0, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    payload.concurrent_limit,
                    payload.storage_limit_mb,
                    now,
                    now,
                ),
            )
    except Exception as exc:
        raise HTTPException(status_code=409, detail="账号已存在或数据不合法。") from exc
    audit_log(
        actor_id=user["id"],
        action="user.create",
        target_type="user",
        target_id=user_id,
        details={"username": payload.username, "role": payload.role},
    )
    return {
        "user_id": user_id,
        "temporary_password": temporary_password,
    }


@router.patch("/users/{target_user_id}")
def update_user(
    target_user_id: str,
    payload: UserPatchRequest,
    user: dict = Depends(require_csrf_user),
) -> dict:
    _admin(user)
    _validate_role(payload.role)
    _validate_status(payload.status)
    now = utc_now()
    quota_snapshot = get_user_quota(target_user_id)
    with transaction() as conn:
        existing = conn.execute("SELECT * FROM users WHERE id = ?", (target_user_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="用户不存在。")
        if payload.display_name is not None:
            conn.execute(
                "UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?",
                (payload.display_name.strip(), now, target_user_id),
            )
        if payload.role is not None:
            conn.execute(
                "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
                (payload.role, now, target_user_id),
            )
        if payload.status is not None:
            conn.execute(
                "UPDATE users SET status = ?, updated_at = ? WHERE id = ?",
                (payload.status, now, target_user_id),
            )
        if payload.concurrent_limit is not None or payload.storage_limit_mb is not None:
            conn.execute(
                """
                UPDATE user_quotas
                SET concurrent_limit = ?, storage_limit_mb = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (
                    payload.concurrent_limit or quota_snapshot["concurrent_limit"],
                    payload.storage_limit_mb or quota_snapshot["storage_limit_mb"],
                    now,
                    target_user_id,
                ),
            )
        if payload.balance_delta:
            conn.execute(
                """
                UPDATE user_quotas
                SET balance = balance + ?, updated_at = ?
                WHERE user_id = ?
                """,
                (payload.balance_delta, now, target_user_id),
            )
            conn.execute(
                """
                INSERT INTO quota_transactions (
                  id, user_id, amount, reason, operator_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("qtx"),
                    target_user_id,
                    payload.balance_delta,
                    payload.balance_reason,
                    user["id"],
                    now,
                ),
            )
    audit_log(
        actor_id=user["id"],
        action="user.update",
        target_type="user",
        target_id=target_user_id,
        details=payload.dict(exclude_none=True),
    )
    return {"status": "ok"}


@router.post("/users/{target_user_id}/password-reset")
def reset_password(target_user_id: str, user: dict = Depends(require_csrf_user)) -> dict:
    _admin(user)
    temporary_password = make_temporary_password()
    now = utc_now()
    with transaction() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (target_user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在。")
        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, must_change_password = 1, updated_at = ?
            WHERE id = ?
            """,
            (hash_password(temporary_password), now, target_user_id),
        )
        conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (now, target_user_id),
        )
    audit_log(
        actor_id=user["id"],
        action="user.password_reset",
        target_type="user",
        target_id=target_user_id,
    )
    return {"temporary_password": temporary_password}


@router.delete("/users/{target_user_id}")
def delete_user(target_user_id: str, user: dict = Depends(require_csrf_user)) -> dict:
    _admin(user)
    if target_user_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能删除当前登录管理员。")
    with transaction() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (target_user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在。")
    deleted_files = delete_user_storage(target_user_id)
    with transaction() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (target_user_id,))
    audit_log(
        actor_id=user["id"],
        action="user.delete",
        target_type="user",
        target_id=target_user_id,
    )
    return {"status": "deleted", "deleted_files": deleted_files}


@router.get("/jobs")
def admin_jobs(user: dict = Depends(require_csrf_user)) -> dict:
    _admin(user)
    return {"data": list_jobs(limit=200)}


@router.get("/jobs/{job_id}/logs")
def admin_job_logs(job_id: str, user: dict = Depends(require_csrf_user)) -> dict:
    _admin(user)
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return collect_job_log_entries(job)


@router.get("/settings")
def admin_settings(
    reveal_secrets: bool = Query(default=False),
    user: dict = Depends(require_csrf_user),
) -> dict:
    _admin(user)
    return {"settings": get_admin_global_settings(reveal_secrets=reveal_secrets)}


@router.put("/settings")
def update_admin_settings(
    payload: GlobalSettingsRequest,
    user: dict = Depends(require_csrf_user),
) -> dict:
    _admin(user)
    settings = save_global_settings(payload.settings, actor_id=user["id"])
    audit_log(
        actor_id=user["id"],
        action="settings.update",
        target_type="global_settings",
        target_id="default",
        details={"keys": sorted(payload.settings.keys())},
    )
    return {"settings": get_admin_global_settings()}
