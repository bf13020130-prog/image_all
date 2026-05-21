from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from .config import CONFIG
from .database import connect, new_id, transaction
from .security import utc_now


def user_storage_dir(user_id: str) -> Path:
    path = CONFIG.storage_dir / "users" / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_storage_dir(user_id: str, job_id: str) -> Path:
    path = user_storage_dir(user_id) / "jobs" / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _users_storage_root() -> Path:
    return (CONFIG.storage_dir / "users").resolve()


def _safe_storage_child(*parts: str) -> Path:
    root = _users_storage_root()
    target = root.joinpath(*parts).resolve()
    target.relative_to(root)
    return target


def delete_job_storage(user_id: str, job_id: str) -> bool:
    target = _safe_storage_child(user_id, "jobs", job_id)
    if not target.exists():
        return False
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return True


def delete_user_storage(user_id: str) -> bool:
    target = _safe_storage_child(user_id)
    if not target.exists():
        return False
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return True


def safe_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
        return suffix
    return ".bin"


async def save_uploads(
    *,
    user_id: str,
    job_id: str,
    files: list[UploadFile] | None,
    field_name: str,
) -> list[dict[str, Any]]:
    if not files:
        return []
    saved: list[dict[str, Any]] = []
    target_dir = job_storage_dir(user_id, job_id) / "inputs"
    target_dir.mkdir(parents=True, exist_ok=True)
    for index, upload in enumerate(files, start=1):
        content = await upload.read()
        if not content:
            continue
        if len(content) > CONFIG.max_upload_mb * 1024 * 1024:
            raise ValueError(f"{upload.filename or field_name} 超过上传大小限制。")
        suffix = safe_suffix(upload.filename or "")
        target = target_dir / f"{field_name}-{index:02d}{suffix}"
        target.write_bytes(content)
        saved.append(
            {
                "field": field_name,
                "filename": upload.filename or target.name,
                "path": str(target),
                "url": f"/api/v1/files/{user_id}/jobs/{job_id}/inputs/{target.name}",
                "size_bytes": len(content),
                "mime_type": upload.content_type
                or mimetypes.guess_type(target.name)[0]
                or "application/octet-stream",
            }
        )
    return saved


def register_artifact(
    *,
    job_id: str,
    user_id: str,
    kind: str,
    path: Path,
    url: str,
    mime_type: str = "",
) -> dict[str, Any]:
    size_bytes = path.stat().st_size if path.exists() else 0
    artifact = {
        "id": new_id("art"),
        "job_id": job_id,
        "user_id": user_id,
        "kind": kind,
        "path": str(path),
        "url": url,
        "size_bytes": size_bytes,
        "mime_type": mime_type or mimetypes.guess_type(path.name)[0] or "",
        "created_at": utc_now(),
    }
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO job_artifacts (
              id, job_id, user_id, kind, path, url, size_bytes, mime_type, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact["id"],
                artifact["job_id"],
                artifact["user_id"],
                artifact["kind"],
                artifact["path"],
                artifact["url"],
                artifact["size_bytes"],
                artifact["mime_type"],
                artifact["created_at"],
            ),
        )
        conn.execute(
            """
            UPDATE jobs
            SET storage_bytes = (
              SELECT COALESCE(SUM(size_bytes), 0) FROM job_artifacts WHERE job_id = ?
            ),
            updated_at = ?
            WHERE id = ?
            """,
            (job_id, utc_now(), job_id),
        )
    return artifact


def storage_used_by_user(user_id: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM job_artifacts WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return int(row["total"] if row else 0)
