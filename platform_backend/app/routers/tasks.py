from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..auth import require_active_user, require_csrf_user
from ..database import json_loads
from ..storage_service import save_uploads
from ..task_service import (
    create_job,
    finish_job,
    get_job,
    list_job_events,
    list_jobs,
    update_job_payload,
)


router = APIRouter(prefix="/api/v1", tags=["tasks"])


@router.get("/jobs")
def get_jobs(user: dict = Depends(require_active_user)) -> dict:
    return {"data": list_jobs(user_id=user["id"])}


@router.get("/jobs/{job_id}")
def get_one_job(job_id: str, user: dict = Depends(require_active_user)) -> dict:
    job = get_job(job_id, user_id=user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return job


@router.get("/jobs/{job_id}/events")
def get_events(job_id: str, user: dict = Depends(require_active_user)) -> dict:
    if not get_job(job_id, user_id=user["id"]):
        raise HTTPException(status_code=404, detail="任务不存在。")
    return {"data": list_job_events(job_id, user_id=user["id"])}


@router.post("/tasks/{task_type}")
async def create_task(
    task_type: str,
    title: str = Form(""),
    payload_json: str = Form("{}"),
    files: list[UploadFile] | None = File(default=None),
    user: dict = Depends(require_csrf_user),
) -> dict:
    payload: dict[str, Any] = json_loads(payload_json, {})
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload_json 必须是 JSON 对象。")
    job = create_job(
        user_id=user["id"],
        task_type=task_type,
        payload=payload,
        title=title.strip() or None,
    )
    try:
        uploads = await save_uploads(
            user_id=user["id"],
            job_id=job["id"],
            files=files,
            field_name="input",
        )
    except Exception as exc:
        finish_job(
            job_id=job["id"],
            user_id=user["id"],
            status="failed",
            result={},
            error=str(exc),
            progress=100,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if uploads:
        payload["uploads"] = uploads
        update_job_payload(job["id"], payload)
        job = get_job(job["id"], user_id=user["id"]) or job
    return {"job": job, "uploads": uploads}
