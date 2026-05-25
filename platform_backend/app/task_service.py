from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Iterator

from fastapi import HTTPException

from .database import connect, json_dumps, json_loads, new_id, row_to_dict, transaction
from .security import utc_now
from .settings_service import effective_settings_for_user
from .storage_service import delete_job_storage, storage_used_by_user


HISTORICAL_JOB_STATUSES = ("completed", "partial", "failed", "cancelled")


def _history_cutoff(days: int) -> str:
    safe_days = max(1, int(days))
    return (datetime.utcnow() - timedelta(days=safe_days)).isoformat(timespec="seconds") + "Z"


VALID_TASK_TYPES = {
    "style-replicate": "复刻风格图片",
    "style-replicate-v2": "复刻风格图片2",
    "image-edit": "图片生成",
    "image-agent": "图片生成 Agent",
    "color-match": "一键追色",
}


def audit_log(
    *,
    actor_id: str | None,
    action: str,
    target_type: str,
    target_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO audit_logs (
              id, actor_id, action, target_type, target_id, details_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("aud"),
                actor_id,
                action,
                target_type,
                target_id,
                json_dumps(details or {}),
                utc_now(),
            ),
        )


def add_job_event(
    *,
    job_id: str,
    user_id: str,
    message: str,
    level: str = "info",
) -> None:
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO job_events (id, job_id, user_id, level, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (new_id("evt"), job_id, user_id, level, message, utc_now()),
        )


def allocate_user_image_sequence(
    *,
    user_id: str,
    count: int,
    counter_key: str = "generated_images",
) -> int:
    safe_count = max(1, int(count))
    now = utc_now()
    with transaction() as conn:
        row = conn.execute(
            """
            SELECT next_value FROM user_image_counters
            WHERE user_id = ? AND counter_key = ?
            """,
            (user_id, counter_key),
        ).fetchone()
        if row:
            start = max(1, int(row["next_value"] or 1))
            conn.execute(
                """
                UPDATE user_image_counters
                SET next_value = ?, updated_at = ?
                WHERE user_id = ? AND counter_key = ?
                """,
                (start + safe_count, now, user_id, counter_key),
            )
        else:
            start = 1
            conn.execute(
                """
                INSERT INTO user_image_counters (
                  user_id, counter_key, next_value, updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (user_id, counter_key, start + safe_count, now),
            )
    return start


def create_job(
    *,
    user_id: str,
    task_type: str,
    payload: dict[str, Any],
    title: str | None = None,
) -> dict[str, Any]:
    if task_type not in VALID_TASK_TYPES:
        raise HTTPException(status_code=400, detail="不支持的任务类型。")
    quota = get_user_quota(user_id)
    used_storage = storage_used_by_user(user_id)
    storage_limit = int(quota.get("storage_limit_mb") or 0) * 1024 * 1024
    if storage_limit and used_storage >= storage_limit:
        raise HTTPException(status_code=403, detail="用户存储空间已用尽。")
    job_id = new_id("job")
    now = utc_now()
    settings = effective_settings_for_user(user_id)
    job_title = title or VALID_TASK_TYPES[task_type]
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO jobs (
              id, user_id, task_type, title, status, progress, payload_json,
              effective_settings_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?)
            """,
            (
                job_id,
                user_id,
                task_type,
                job_title,
                json_dumps(payload),
                json_dumps(settings),
                now,
                now,
            ),
        )
    add_job_event(job_id=job_id, user_id=user_id, message="任务已提交，等待 Worker 执行。")
    return get_job(job_id, user_id=user_id) or {}


def update_job_payload(job_id: str, payload: dict[str, Any]) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE jobs SET payload_json = ?, updated_at = ? WHERE id = ?",
            (json_dumps(payload), utc_now(), job_id),
        )


def update_running_job_result(
    *,
    job_id: str,
    user_id: str,
    result: dict[str, Any],
    progress: int | None = None,
) -> None:
    now = utc_now()
    safe_progress = None
    if progress is not None:
        safe_progress = max(5, min(99, int(progress)))
    with transaction() as conn:
        if safe_progress is None:
            conn.execute(
                """
                UPDATE jobs
                SET result_json = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'running'
                """,
                (json_dumps(result), now, job_id, user_id),
            )
        else:
            conn.execute(
                """
                UPDATE jobs
                SET result_json = ?, progress = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'running'
                """,
                (json_dumps(result), safe_progress, now, job_id, user_id),
            )


def get_user_quota(user_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM user_quotas WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    quota = row_to_dict(row)
    if quota:
        return quota
    now = utc_now()
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO user_quotas (
              user_id, balance, daily_limit, monthly_limit, concurrent_limit,
              storage_limit_mb, created_at, updated_at
            )
            VALUES (?, 0, 0, 0, 20, 10240, ?, ?)
            """,
            (user_id, now, now),
        )
    return get_user_quota(user_id)


def count_running_jobs(user_id: str) -> int:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count FROM jobs
            WHERE user_id = ? AND status IN ('queued', 'running')
            """,
            (user_id,),
        ).fetchone()
    return int(row["count"] if row else 0)


def count_active_request_slots(user_id: str) -> int:
    cleanup_orphan_request_slots(user_id=user_id)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count FROM active_request_slots
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    return int(row["count"] if row else 0)


def _cleanup_orphan_request_slots(conn: Any, *, user_id: str | None = None) -> int:
    params: list[Any] = []
    user_filter = ""
    if user_id:
        user_filter = "AND user_id = ?"
        params.append(user_id)
    cursor = conn.execute(
        f"""
        DELETE FROM active_request_slots
        WHERE NOT EXISTS (
            SELECT 1 FROM jobs
            WHERE jobs.id = active_request_slots.job_id
              AND jobs.user_id = active_request_slots.user_id
              AND jobs.status IN ('queued', 'running')
        )
        {user_filter}
        """,
        params,
    )
    return int(cursor.rowcount or 0)


def cleanup_orphan_request_slots(*, user_id: str | None = None) -> int:
    with transaction() as conn:
        return _cleanup_orphan_request_slots(conn, user_id=user_id)


def release_job_request_slots(job_id: str, user_id: str) -> int:
    with transaction() as conn:
        cursor = conn.execute(
            "DELETE FROM active_request_slots WHERE job_id = ? AND user_id = ?",
            (job_id, user_id),
        )
    return int(cursor.rowcount or 0)


@contextmanager
def request_slot(
    *,
    user_id: str,
    job_id: str,
    label: str = "",
    poll_seconds: float = 0.5,
) -> Iterator[None]:
    slot_id = new_id("slot")
    safe_poll_seconds = max(0.1, float(poll_seconds or 0.5))
    while True:
        quota = get_user_quota(user_id)
        capacity = max(1, int(quota.get("concurrent_limit") or 20))
        now = utc_now()
        acquired = False
        with transaction() as conn:
            _cleanup_orphan_request_slots(conn, user_id=user_id)
            row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM active_request_slots
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            used = int(row["count"] if row else 0)
            if used < capacity:
                conn.execute(
                    """
                    INSERT INTO active_request_slots (
                      id, user_id, job_id, label, acquired_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (slot_id, user_id, job_id, str(label or ""), now, now),
                )
                acquired = True
        if acquired:
            break
        time.sleep(safe_poll_seconds)

    try:
        yield
    finally:
        with transaction() as conn:
            conn.execute("DELETE FROM active_request_slots WHERE id = ?", (slot_id,))


def _public_job(row: dict[str, Any]) -> dict[str, Any]:
    payload = json_loads(row.get("payload_json"), {})
    result = json_loads(row.get("result_json"), {})
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "task_type": row["task_type"],
        "title": row["title"],
        "status": row["status"],
        "progress": row["progress"],
        "payload": payload,
        "result": result,
        "error": row.get("error", ""),
        "storage_bytes": row.get("storage_bytes", 0),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
    }


def _worker_job(row: dict[str, Any]) -> dict[str, Any]:
    job = _public_job(row)
    job["effective_settings"] = json_loads(row.get("effective_settings_json"), {})
    return job


def list_jobs(
    *,
    user_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(limit, 200)))
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [_public_job(row_to_dict(row) or {}) for row in rows]


def cleanup_expired_job_history(*, retention_days: int) -> int:
    cutoff = _history_cutoff(retention_days)
    status_clause = ",".join("?" for _ in HISTORICAL_JOB_STATUSES)
    batch_size = 200
    removed = 0

    while True:
        with connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, user_id
                FROM jobs
                WHERE status IN ({status_clause})
                  AND COALESCE(finished_at, updated_at, created_at) < ?
                ORDER BY COALESCE(finished_at, updated_at, created_at) ASC
                LIMIT ?
                """,
                (*HISTORICAL_JOB_STATUSES, cutoff, batch_size),
            ).fetchall()

        if not rows:
            break

        for row in rows:
            job_id = str(row["id"])
            user_id = str(row["user_id"])
            try:
                delete_job_storage(user_id, job_id)
            except Exception:
                pass
            with transaction() as conn:
                cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                removed += int(cursor.rowcount or 0)

        if len(rows) < batch_size:
            break

    return removed


def get_job(job_id: str, *, user_id: str | None = None) -> dict[str, Any] | None:
    params: list[Any] = [job_id]
    where = "id = ?"
    if user_id:
        where += " AND user_id = ?"
        params.append(user_id)
    with connect() as conn:
        row = conn.execute(f"SELECT * FROM jobs WHERE {where}", params).fetchone()
    job = row_to_dict(row)
    return _public_job(job) if job else None


def list_job_events(job_id: str, *, user_id: str | None = None) -> list[dict[str, Any]]:
    params: list[Any] = [job_id]
    where = "job_id = ?"
    if user_id:
        where += " AND user_id = ?"
        params.append(user_id)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM job_events WHERE {where} ORDER BY created_at ASC",
            params,
        ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def claim_next_job() -> dict[str, Any] | None:
    with transaction() as conn:
        row = conn.execute(
            """
            SELECT * FROM jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        job = row_to_dict(row) or {}
        now = utc_now()
        conn.execute(
            """
            UPDATE jobs
            SET status = 'running', progress = 5, started_at = ?, updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (now, now, job["id"]),
        )
    add_job_event(job_id=job["id"], user_id=job["user_id"], message="Worker 已开始执行任务。")
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job["id"],)).fetchone()
    return _worker_job(row_to_dict(row) or {}) if row else None


def finish_job(
    *,
    job_id: str,
    user_id: str,
    status: str,
    result: dict[str, Any],
    error: str = "",
    progress: int = 100,
) -> None:
    now = utc_now()
    with transaction() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = ?, progress = ?, result_json = ?, error = ?,
                finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, progress, json_dumps(result), error, now, now, job_id),
        )
        conn.execute(
            "DELETE FROM active_request_slots WHERE job_id = ? AND user_id = ?",
            (job_id, user_id),
        )
    if status == "completed":
        message = "任务完成。"
    elif status == "partial":
        message = f"任务部分完成：{error}" if error else "任务部分完成。"
    else:
        message = f"任务失败：{error}" if error else "任务失败。"
    level = "error" if status == "failed" or error else "warning" if status == "partial" else "info"
    add_job_event(job_id=job_id, user_id=user_id, message=message, level=level)
