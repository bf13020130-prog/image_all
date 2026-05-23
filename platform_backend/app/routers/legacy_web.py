from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..auth import require_active_user, require_csrf_user
from ..database import transaction
from ..download_service import build_job_zip, collect_job_download_files
from ..legacy_contract import collect_job_log_entries, serialize_job as serialize_legacy_job
from ..settings_service import (
    get_user_secrets,
    get_user_settings,
    public_settings_for_user,
    save_user_secrets,
    save_user_settings,
)
from ..storage_service import delete_job_storage, save_uploads
from ..task_service import create_job, finish_job, get_job, get_user_quota, list_jobs, update_job_payload
from ..task_service import count_running_jobs
from ..config import CONFIG


router = APIRouter(prefix="/api", tags=["legacy-web"])


def _shared_pool(user_id: str) -> dict[str, int | str]:
    settings = public_settings_for_user(user_id)["effective"]
    quota = get_user_quota(user_id)
    capacity = max(1, int(quota.get("concurrent_limit") or 20))
    used = min(capacity, count_running_jobs(user_id))
    task_concurrency = max(1, int(settings.get("default_concurrency") or 1))
    worker_capacity = max(1, int(CONFIG.worker_concurrency))
    running = sum(
        1 for item in list_jobs(status="running", limit=worker_capacity + 50)
        if item.get("status") == "running"
    )
    return {
        "size": capacity,
        "capacity": capacity,
        "used": used,
        "available": max(0, capacity - used),
        "task_concurrency": min(task_concurrency, capacity),
        "worker_capacity": worker_capacity,
        "worker_used": min(worker_capacity, running),
        "worker_available": max(0, worker_capacity - running),
    }


def _read_summary_file(record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    path_text = str(record.get("summary_file") or "")
    if not path_text:
        return {}
    try:
        path = Path(path_text)
        if not path.exists() or not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _legacy_summary(
    result: dict[str, Any],
    record: dict[str, Any] | None,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_summary = result.get("summary")
    summary = dict(raw_summary) if isinstance(raw_summary, dict) else _read_summary_file(record)
    if result.get("message") and not summary.get("message"):
        summary["message"] = result.get("message")
    summary["artifacts"] = artifacts
    return summary


def _legacy_job(job: dict[str, Any]) -> dict[str, Any]:
    return serialize_legacy_job(job)


def _legacy_job_old(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    record = result.get("record") if isinstance(result.get("record"), dict) else None
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
    summary = _legacy_summary(result, record, artifacts)
    return {
        "job_id": job["id"],
        "task_key": job["task_type"],
        "title": job["title"],
        "status": job["status"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "logs": [],
        "error": job.get("error", ""),
        "error_detail": None,
        "metadata": {
            **(job.get("payload") if isinstance(job.get("payload"), dict) else {}),
            "storage_bytes": job.get("storage_bytes", 0),
        },
        "record": _legacy_record(job, record, artifacts) if record or artifacts else None,
        "summary": summary,
    }


def _legacy_record(
    job: dict[str, Any],
    record: dict[str, Any] | None,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    image_artifacts = [
        item
        for item in artifacts
        if isinstance(item, dict)
        and (
            str(item.get("kind") or "").startswith("image")
            or str(item.get("mime_type") or "").startswith("image/")
        )
    ]
    latest_urls = [str(item.get("url")) for item in image_artifacts if item.get("url")]
    base = record if isinstance(record, dict) else {}
    summary = _legacy_summary(
        job.get("result") if isinstance(job.get("result"), dict) else {},
        record,
        artifacts,
    )
    return {
        **base,
        "run_id": base.get("run_id") or job["id"],
        "task_key": job["task_type"],
        "title": job["title"],
        "status": job["status"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "latest_image_urls": latest_urls,
        "latest_thumbnail_urls": latest_urls,
        "latest_image_items": [
            {"url": url, "thumbnail_url": url, "path": url}
            for url in latest_urls
        ],
        "summary": summary,
        "download_url": "",
        "open_url": "",
    }


def _legacy_history(user_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for job in list_jobs(user_id=user_id, limit=200):
        if job["status"] not in {"completed", "partial", "failed"}:
            continue
        legacy_job = _legacy_job(job)
        record = legacy_job.get("record")
        if record:
            records.append(record)
    return records


def _job_for_run_id(run_id: str, user_id: str) -> dict[str, Any] | None:
    if not run_id:
        return None
    direct = get_job(run_id, user_id=user_id)
    if direct:
        return direct
    for item in list_jobs(user_id=user_id, limit=200):
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        record = result.get("record") if isinstance(result.get("record"), dict) else {}
        if str(record.get("run_id") or "") == run_id:
            return item
    return None


def _download_response(job: dict[str, Any], *, scope: str, selected_ids: set[str] | None = None) -> FileResponse:
    try:
        target, filename = build_job_zip(job, scope=scope, selected_ids=selected_ids)
    except ValueError as exc:
        if str(exc) == "no_files":
            raise HTTPException(status_code=404, detail="该任务没有可下载文件。") from exc
        raise
    return FileResponse(
        target,
        media_type="application/zip",
        filename=filename,
    )


def _delete_job_for_user(item: dict[str, Any], user_id: str, *, run_id: str | None = None) -> dict[str, Any]:
    if item["status"] in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="task_still_running")
    deleted_files = delete_job_storage(user_id, item["id"])
    with transaction() as conn:
        conn.execute(
            "DELETE FROM jobs WHERE id = ? AND user_id = ?",
            (item["id"], user_id),
        )
    return {
        "status": "deleted",
        "run_id": run_id or item["id"],
        "job_id": item["id"],
        "deleted_files": deleted_files,
    }


def _conversation_id_for_job(item: dict[str, Any]) -> str:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    payload_conversation_id = str(payload.get("conversation_id") or "").strip()
    if payload_conversation_id:
        return payload_conversation_id
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    record = result.get("record") if isinstance(result.get("record"), dict) else {}
    return str(record.get("conversation_id") or "").strip()


def _task_response(job: dict[str, Any]) -> dict[str, Any]:
    shared_pool = _shared_pool(job["user_id"])
    return {
        "job_id": job["id"],
        "status": job["status"],
        "shared_pool_size": shared_pool["capacity"],
        "shared_pool": shared_pool,
    }


def _json_or_empty(value: str) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def _looks_like_masked_secret(value: Any) -> bool:
    text = str(value or "")
    return "***" in text or "..." in text


def _settings_for_legacy_form(user_id: str) -> dict[str, Any]:
    payload = public_settings_for_user(user_id)
    defaults = payload["defaults"]
    effective = payload["effective"]
    secret_keys = set(payload["secret_keys"])
    user_secrets = get_user_secrets(user_id, reveal=True)
    settings = dict(defaults)
    settings.update(
        {
            key: value
            for key, value in effective.items()
            if key not in secret_keys and value not in ("", None)
        }
    )
    for key in secret_keys:
        settings[key] = user_secrets.get(key, "")
    settings["_secret_keys"] = list(payload["secret_keys"])
    settings["_secret_status"] = payload.get("secret_status", {})
    return settings


@router.post("/client-log")
async def client_log() -> dict[str, str]:
    return {"status": "ignored"}


@router.get("/bootstrap")
def bootstrap(user: dict = Depends(require_active_user)) -> dict[str, Any]:
    settings = _settings_for_legacy_form(user["id"])
    return {
        "app_title": "设计出图",
        "pages": [
            {"key": "style-replicate", "label": "复刻风格图片"},
            {"key": "style-replicate-v2", "label": "复刻风格图片2"},
            {"key": "image-edit", "label": "图片生成"},
            {"key": "color-match", "label": "一键追色"},
            {"key": "history", "label": "历史"},
            {"key": "settings", "label": "设置"},
        ],
        "settings": settings,
        "shared_pool": _shared_pool(user["id"]),
        "history": _legacy_history(user["id"]),
        "jobs": [_legacy_job(item) for item in list_jobs(user_id=user["id"], limit=20)],
        "edit_conversations": [],
    }


@router.get("/settings")
def get_settings(user: dict = Depends(require_active_user)) -> dict[str, Any]:
    return _settings_for_legacy_form(user["id"])


@router.put("/settings")
def update_settings(
    payload: dict[str, Any],
    user: dict = Depends(require_csrf_user),
) -> dict[str, Any]:
    settings_payload = public_settings_for_user(user["id"])
    secret_keys = set(settings_payload["secret_keys"])
    current_user_settings = get_user_settings(user["id"])
    settings = {
        **current_user_settings,
        **{
            key: value
            for key, value in payload.items()
            if key not in secret_keys and value not in ("", None)
        },
    }
    secrets = {
        key: value
        for key, value in payload.items()
        if key in secret_keys and value and not _looks_like_masked_secret(value)
    }
    save_user_settings(user["id"], settings)
    if secrets:
        save_user_secrets(user["id"], secrets)
    return _settings_for_legacy_form(user["id"])


@router.get("/shared-pool")
def shared_pool(user: dict = Depends(require_active_user)) -> dict[str, int]:
    return _shared_pool(user["id"])


@router.get("/history")
def history(user: dict = Depends(require_active_user)) -> list[dict[str, Any]]:
    return _legacy_history(user["id"])


@router.get("/jobs")
def jobs(user: dict = Depends(require_active_user)) -> list[dict[str, Any]]:
    return [_legacy_job(item) for item in list_jobs(user_id=user["id"], limit=100)]


@router.get("/jobs/{job_id}")
def job(job_id: str, user: dict = Depends(require_active_user)) -> dict[str, Any]:
    item = get_job(job_id, user_id=user["id"])
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return _legacy_job(item)


@router.get("/jobs/{job_id}/files")
def job_files(job_id: str, user: dict = Depends(require_active_user)) -> dict[str, Any]:
    item = get_job(job_id, user_id=user["id"])
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在。")
    files = collect_job_download_files(item)
    image_files = [file.public_dict() for file in files["images"]]
    package_files = [file.public_dict() for file in files["package_files"]]
    return {
        "job_id": job_id,
        "image_count": len(image_files),
        "package_file_count": len(package_files),
        "images": image_files,
        "package_files": package_files,
    }


@router.get("/jobs/{job_id}/download")
def download_job(
    job_id: str,
    scope: str = "images",
    user: dict = Depends(require_active_user),
) -> FileResponse:
    item = get_job(job_id, user_id=user["id"])
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return _download_response(item, scope=scope)


@router.delete("/jobs/{job_id}")
def delete_job(
    job_id: str,
    user: dict = Depends(require_csrf_user),
) -> dict[str, Any]:
    item = get_job(job_id, user_id=user["id"])
    if not item:
        raise HTTPException(status_code=404, detail="task_not_found")
    return _delete_job_for_user(item, user["id"])


@router.post("/jobs/{job_id}/download-selected")
def download_selected_job_files(
    job_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    user: dict = Depends(require_csrf_user),
) -> FileResponse:
    item = get_job(job_id, user_id=user["id"])
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在。")
    body = payload if isinstance(payload, dict) else {}
    selected_ids = {
        str(file_id)
        for file_id in body.get("file_ids", [])
        if str(file_id).strip()
    }
    if not selected_ids:
        raise HTTPException(status_code=400, detail="请选择要下载的文件。")
    return _download_response(
        item,
        scope=str(body.get("scope") or "images"),
        selected_ids=selected_ids,
    )


@router.get("/runs/{run_id}/download")
def download_run(
    run_id: str,
    scope: str = "images",
    user: dict = Depends(require_active_user),
) -> FileResponse:
    item = _job_for_run_id(run_id, user["id"])
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return _download_response(item, scope=scope)


@router.delete("/runs/{run_id}")
def delete_run(
    run_id: str,
    user: dict = Depends(require_csrf_user),
) -> dict[str, Any]:
    item = _job_for_run_id(run_id, user["id"])
    if not item:
        raise HTTPException(status_code=404, detail="task_not_found")
    return _delete_job_for_user(item, user["id"], run_id=run_id)


@router.get("/edit-conversations")
def edit_conversations(_user: dict = Depends(require_active_user)) -> dict[str, Any]:
    return {"conversations": []}


@router.post("/edit-conversations")
@router.put("/edit-conversations")
def update_edit_conversations(
    _payload: Any = Body(default=None),
    _user: dict = Depends(require_csrf_user),
) -> dict[str, Any]:
    return {"status": "ok", "count": 0}


@router.delete("/edit-conversations/{conversation_id}")
def delete_edit_conversation(
    conversation_id: str,
    user: dict = Depends(require_csrf_user),
) -> dict[str, Any]:
    target_conversation_id = str(conversation_id or "").strip()
    if not target_conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id_required")

    deleted_run_ids: list[str] = []
    deleted_job_ids: list[str] = []
    skipped_job_ids: list[str] = []

    for item in list_jobs(user_id=user["id"], limit=200):
        if item.get("task_type") not in {"image-edit", "image-agent"}:
            continue
        if _conversation_id_for_job(item) != target_conversation_id:
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        record = result.get("record") if isinstance(result.get("record"), dict) else {}
        run_id = str(record.get("run_id") or item["id"])
        if item.get("status") in {"queued", "running"}:
            skipped_job_ids.append(item["id"])
            continue
        deleted = _delete_job_for_user(item, user["id"], run_id=run_id)
        deleted_run_ids.append(str(deleted.get("run_id") or run_id))
        deleted_job_ids.append(str(deleted.get("job_id") or item["id"]))

    return {
        "status": "deleted",
        "deleted_run_ids": deleted_run_ids,
        "deleted_job_ids": deleted_job_ids,
        "skipped_job_ids": skipped_job_ids,
    }


@router.get("/logs")
def logs(
    job_id: str | None = None,
    run_id: str | None = None,
    user: dict = Depends(require_active_user),
) -> dict[str, Any]:
    selected_job = get_job(job_id, user_id=user["id"]) if job_id else None
    if not selected_job and run_id:
        for item in list_jobs(user_id=user["id"], limit=200):
            result = item.get("result") if isinstance(item.get("result"), dict) else {}
            record = result.get("record") if isinstance(result.get("record"), dict) else {}
            if str(record.get("run_id") or "") == run_id:
                selected_job = item
                break
    if not selected_job:
        selected_job = next(iter(list_jobs(user_id=user["id"], limit=1)), None)
    if not selected_job:
        return {"entries": [], "selected_key": "events"}
    return collect_job_log_entries(selected_job)


@router.post("/logs/open")
@router.post("/data/open")
def desktop_only(_user: dict = Depends(require_csrf_user)) -> dict[str, str]:
    raise HTTPException(status_code=400, detail="Web 版本不能打开服务器本地目录。")


@router.get("/clipboard/images")
def clipboard_images(_user: dict = Depends(require_active_user)) -> dict[str, Any]:
    return {"items": []}


@router.post("/tasks/style-replicate")
async def create_style_replicate(
    prompt_count: str = Form(""),
    output_resolution: str = Form(""),
    output_aspect_ratio: str = Form(""),
    aspect_ratio: str = Form(""),
    user_prompt: str = Form(""),
    style_url: str = Form(""),
    product_url: str = Form(""),
    style_file: list[UploadFile] | None = File(default=None),
    product_file: list[UploadFile] | None = File(default=None),
    user: dict = Depends(require_csrf_user),
) -> dict[str, Any]:
    payload = {
        "prompt_count": int(prompt_count or 0) or None,
        "output_resolution": output_resolution,
        "output_aspect_ratio": output_aspect_ratio,
        "aspect_ratio": aspect_ratio,
        "prompt": user_prompt,
        "user_prompt": user_prompt,
        "style_url": style_url,
        "product_url": product_url,
    }
    return await _create_legacy_task(
        user=user,
        task_type="style-replicate",
        title="复刻风格图片",
        payload=payload,
        file_groups=[("style", style_file), ("product", product_file)],
    )


@router.post("/tasks/style-replicate-v2")
async def create_style_replicate_v2(
    prompt_count: str = Form(""),
    output_resolution: str = Form(""),
    output_aspect_ratio: str = Form(""),
    aspect_ratio: str = Form(""),
    user_prompt: str = Form(""),
    reference_url: str = Form(""),
    reference_file: list[UploadFile] | None = File(default=None),
    user: dict = Depends(require_csrf_user),
) -> dict[str, Any]:
    payload = {
        "prompt_count": int(prompt_count or 0) or None,
        "output_resolution": output_resolution,
        "output_aspect_ratio": output_aspect_ratio,
        "aspect_ratio": aspect_ratio,
        "prompt": user_prompt,
        "user_prompt": user_prompt,
        "reference_url": reference_url,
    }
    return await _create_legacy_task(
        user=user,
        task_type="style-replicate-v2",
        title="复刻风格图片2",
        payload=payload,
        file_groups=[("reference", reference_file)],
    )


@router.post("/tasks/image-edit")
async def create_image_edit(
    prompt: str = Form(""),
    image_model: str = Form(""),
    output_resolution: str = Form(""),
    output_aspect_ratio: str = Form(""),
    images_per_prompt: str = Form(""),
    conversation_id: str = Form(""),
    conversation_title: str = Form(""),
    input_files: list[UploadFile] | None = File(default=None),
    user: dict = Depends(require_csrf_user),
) -> dict[str, Any]:
    payload = {
        "prompt": prompt,
        "image_model": image_model,
        "output_resolution": output_resolution,
        "output_aspect_ratio": output_aspect_ratio,
        "images_per_prompt": int(images_per_prompt or 0) or None,
        "conversation_id": conversation_id,
        "conversation_title": conversation_title,
    }
    return await _create_legacy_task(
        user=user,
        task_type="image-edit",
        title=conversation_title or "图片生成",
        payload=payload,
        file_groups=[("input", input_files)],
    )


@router.post("/tasks/image-agent")
async def create_image_agent(
    prompt: str = Form(""),
    image_model: str = Form(""),
    conversation_id: str = Form(""),
    conversation_title: str = Form(""),
    conversation_context: str = Form(""),
    input_files: list[UploadFile] | None = File(default=None),
    user: dict = Depends(require_csrf_user),
) -> dict[str, Any]:
    payload = {
        "prompt": prompt,
        "image_model": image_model,
        "conversation_id": conversation_id,
        "conversation_title": conversation_title,
        "conversation_context": _json_or_empty(conversation_context),
    }
    return await _create_legacy_task(
        user=user,
        task_type="image-agent",
        title=conversation_title or "图片生成 Agent",
        payload=payload,
        file_groups=[("input", input_files)],
    )


@router.post("/tasks/color-match")
async def create_color_match(
    output_resolution: str = Form(""),
    output_aspect_ratio: str = Form(""),
    aspect_ratio: str = Form(""),
    tone_file: UploadFile | None = File(default=None),
    scene_file: UploadFile | None = File(default=None),
    user: dict = Depends(require_csrf_user),
) -> dict[str, Any]:
    payload = {
        "output_resolution": output_resolution,
        "output_aspect_ratio": output_aspect_ratio,
        "aspect_ratio": aspect_ratio,
    }
    return await _create_legacy_task(
        user=user,
        task_type="color-match",
        title="一键追色",
        payload=payload,
        file_groups=[
            ("tone", [tone_file] if tone_file else None),
            ("scene", [scene_file] if scene_file else None),
        ],
    )


async def _create_legacy_task(
    *,
    user: dict,
    task_type: str,
    title: str,
    payload: dict[str, Any],
    file_groups: list[tuple[str, list[UploadFile] | None]],
) -> dict[str, Any]:
    job = create_job(
        user_id=user["id"],
        task_type=task_type,
        payload={key: value for key, value in payload.items() if value not in (None, "")},
        title=title,
    )
    saved_groups: dict[str, list[dict[str, Any]]] = {}
    try:
        for field_name, files in file_groups:
            saved = await save_uploads(
                user_id=user["id"],
                job_id=job["id"],
                files=files,
                field_name=field_name,
            )
            if saved:
                saved_groups[field_name] = saved
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

    if saved_groups:
        next_payload = {key: value for key, value in payload.items() if value not in (None, "")}
        next_payload["uploads"] = [
            item for group in saved_groups.values() for item in group
        ]
        for group_name, items in saved_groups.items():
            next_payload[f"{group_name}_file_paths"] = [item["path"] for item in items]
        if task_type == "color-match":
            tone = saved_groups.get("tone", [])
            scene = saved_groups.get("scene", [])
            if tone:
                next_payload["tone_image"] = tone[0]["path"]
            if scene:
                next_payload["scene_image"] = scene[0]["path"]
        update_job_payload(job["id"], next_payload)
        job = get_job(job["id"], user_id=user["id"]) or job
    return _task_response(job)
