from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .storage_service import job_storage_dir
from .task_service import (
    list_job_events,
    list_recent_audit_logs,
    list_recent_client_logs,
    list_recent_job_events,
)


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
THUMBNAIL_SUFFIXES = {".webp"}
LOG_TAIL_BYTES = 256 * 1024
USER_LOG_LINE_LIMIT = 2000
ADMIN_LOG_LINE_LIMIT = 10000
CHINA_TZ = timezone(timedelta(hours=8))


def read_json_file(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        target = Path(path)
        if not target.exists() or not target.is_file():
            return {}
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def limit_text_lines(content: str, *, max_lines: int | None = None) -> str:
    if not max_lines or max_lines <= 0:
        return content
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content
    omitted = len(lines) - max_lines
    return (
        f"... only showing last {max_lines} lines, omitted {omitted} earlier lines ...\n"
        + "\n".join(lines[-max_lines:])
    )


def read_text_tail(
    path: str | Path | None,
    *,
    max_bytes: int = LOG_TAIL_BYTES,
    max_lines: int | None = None,
) -> str:
    if not path:
        return ""
    try:
        target = Path(path)
        if not target.exists() or not target.is_file():
            return ""
        size = target.stat().st_size
        with target.open("rb") as handle:
            if size > max_bytes:
                handle.seek(max(0, size - max_bytes))
                prefix = f"... only showing last {max_bytes // 1024} KB ...\n"
            else:
                prefix = ""
            data = handle.read()
        return limit_text_lines(
            prefix + data.decode("utf-8", errors="replace"),
            max_lines=max_lines,
        )
    except Exception as exc:
        return f"读取日志失败: {exc}"


def format_china_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        if text.endswith("Z"):
            parsed = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                return text
        return parsed.astimezone(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return text


def with_china_time_fields(item: dict[str, Any], *fields: str) -> dict[str, Any]:
    copy = dict(item)
    for field in fields:
        if field in copy:
            copy[field] = format_china_time(copy.get(field))
    return copy


def _job_data_dir(job: dict[str, Any]) -> Path:
    return job_storage_dir(job["user_id"], job["id"]) / "pipeline" / "data"


def _pipeline_data_relative(path: str | Path | None, job: dict[str, Any]) -> str | None:
    if not path:
        return None
    try:
        resolved = Path(path).expanduser().resolve()
        relative = resolved.relative_to(_job_data_dir(job).resolve())
    except Exception:
        return None
    return quote(relative.as_posix())


def path_to_pipeline_file_url(path: str | Path | None, job: dict[str, Any]) -> str | None:
    relative = _pipeline_data_relative(path, job)
    if not relative:
        return None
    return f"/api/v1/pipeline-files/{job['user_id']}/jobs/{job['id']}/{relative}"


def path_to_pipeline_thumbnail_url(path: str | Path | None, job: dict[str, Any]) -> str | None:
    relative = _pipeline_data_relative(path, job)
    if not relative:
        return None
    return f"/api/v1/pipeline-thumbnails/{job['user_id']}/jobs/{job['id']}/{relative}"


def thumbnail_path_for_image(path: str | Path | None) -> Path | None:
    if not path:
        return None
    try:
        source = Path(path).expanduser().resolve()
    except Exception:
        return None
    return source.parent / "_thumbs" / f"{source.stem}.webp"


def image_thumbnail_url(
    path: str | Path | None,
    job: dict[str, Any],
    *,
    explicit_thumbnail_path: str | Path | None = None,
) -> str | None:
    if explicit_thumbnail_path:
        explicit_url = path_to_pipeline_file_url(explicit_thumbnail_path, job)
        if explicit_url:
            return explicit_url
    thumbnail_path = thumbnail_path_for_image(path)
    if thumbnail_path and thumbnail_path.exists():
        thumbnail_url = path_to_pipeline_file_url(thumbnail_path, job)
        if thumbnail_url:
            return thumbnail_url
    return path_to_pipeline_thumbnail_url(path, job)


def image_url_pair(
    path: str | Path | None,
    job: dict[str, Any],
    *,
    explicit_thumbnail_path: str | Path | None = None,
) -> dict[str, str] | None:
    url = path_to_pipeline_file_url(path, job)
    if not url:
        return None
    return {
        "url": url,
        "thumbnail_url": image_thumbnail_url(
            path,
            job,
            explicit_thumbnail_path=explicit_thumbnail_path,
        )
        or url,
    }


def _image_items_from_paths(paths: Any, job: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(paths, list):
        return []
    items: list[dict[str, str]] = []
    for image_path in paths:
        if not isinstance(image_path, str):
            continue
        pair = image_url_pair(image_path, job)
        if pair:
            items.append(pair)
    return items


def artifact_image_items(artifacts: list[dict[str, Any]]) -> list[dict[str, str]]:
    image_artifacts = [
        item
        for item in artifacts
        if isinstance(item, dict)
        and item.get("url")
        and (
            str(item.get("kind") or "").startswith("image")
            or str(item.get("mime_type") or "").startswith("image/")
        )
    ]
    by_stem: dict[str, list[dict[str, Any]]] = {}
    for item in image_artifacts:
        path_stem = Path(str(item.get("path") or item.get("url") or "")).stem
        stem = path_stem.removesuffix(".thumb")
        by_stem.setdefault(stem, []).append(item)

    items: list[dict[str, str]] = []
    for group in by_stem.values():
        thumbnail = next(
            (
                item
                for item in group
                if Path(str(item.get("path") or item.get("url") or "")).suffix.lower()
                in THUMBNAIL_SUFFIXES
            ),
            None,
        )
        full = next((item for item in group if item is not thumbnail), None) or thumbnail
        if not full or not full.get("url"):
            continue
        full_url = str(full["url"])
        thumbnail_url = str((thumbnail or full).get("url") or full_url)
        items.append(
            {
                "url": full_url,
                "thumbnail_url": thumbnail_url,
                "path": full_url,
            }
        )
    return items


def serialize_summary(summary: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {}

    renders: list[dict[str, Any]] = []
    for item in summary.get("renders", []):
        if not isinstance(item, dict):
            continue
        detail_thumbnail_paths: dict[str, str] = {}
        image_details = item.get("image_details", [])
        if isinstance(image_details, list):
            for detail in image_details:
                if not isinstance(detail, dict):
                    continue
                image_path = str(detail.get("path") or "")
                thumbnail_path = str(detail.get("thumbnail_path") or "")
                if image_path and thumbnail_path:
                    detail_thumbnail_paths[image_path] = thumbnail_path

        image_items: list[dict[str, str]] = []
        image_paths = item.get("images", [])
        if isinstance(image_paths, list):
            for image_path in image_paths:
                if not isinstance(image_path, str):
                    continue
                pair = image_url_pair(
                    image_path,
                    job,
                    explicit_thumbnail_path=detail_thumbnail_paths.get(image_path),
                )
                if pair:
                    image_items.append(pair)

        renders.append(
            {
                **item,
                "response_file_url": path_to_pipeline_file_url(
                    item.get("response_file"),
                    job,
                ),
                "image_urls": [image_item["url"] for image_item in image_items],
                "thumbnail_urls": [
                    image_item["thumbnail_url"] for image_item in image_items
                ],
                "image_items": image_items,
            }
        )

    color_match_outputs = summary.get("color_match_outputs")
    serialized_color_match_outputs: dict[str, Any] | None = None
    if isinstance(color_match_outputs, dict):
        serialized_color_match_outputs = {}
        for key, value in color_match_outputs.items():
            if isinstance(value, dict):
                output_image_items = _image_items_from_paths(value.get("images"), job)
                serialized_color_match_outputs[key] = {
                    **value,
                    "image_urls": [item["url"] for item in output_image_items],
                    "thumbnail_urls": [
                        item["thumbnail_url"] for item in output_image_items
                    ],
                    "image_items": output_image_items,
                }
            else:
                serialized_color_match_outputs[key] = value

    prompts_text = ""
    prompts_file = summary.get("prompts_file")
    if prompts_file:
        prompts_text = read_text_tail(prompts_file)

    return {
        **summary,
        "prompts_file_url": path_to_pipeline_file_url(summary.get("prompts_file"), job),
        "prompt_request_file_url": path_to_pipeline_file_url(
            summary.get("prompt_request_file"),
            job,
        ),
        "prompt_response_file_url": path_to_pipeline_file_url(
            summary.get("prompt_response_file"),
            job,
        ),
        "render_manifest_file_url": path_to_pipeline_file_url(
            summary.get("render_manifest_file"),
            job,
        ),
        "debug_log_file_url": path_to_pipeline_file_url(
            summary.get("debug_log_file"),
            job,
        ),
        "color_analysis_file_url": path_to_pipeline_file_url(
            summary.get("color_analysis_file"),
            job,
        ),
        "desaturated_scene_url": path_to_pipeline_file_url(
            summary.get("desaturated_scene"),
            job,
        ),
        "desaturated_scene_thumbnail_url": path_to_pipeline_file_url(
            summary.get("desaturated_scene_thumbnail"),
            job,
        )
        or image_thumbnail_url(summary.get("desaturated_scene"), job),
        "color_match_outputs": serialized_color_match_outputs,
        "renders": renders,
        "prompts_text": prompts_text,
    }


def serialize_record(
    job: dict[str, Any],
    record: dict[str, Any] | None,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    base = record if isinstance(record, dict) else {}
    artifact_items = artifact_image_items(artifacts)
    if not base and not artifact_items:
        return None

    raw_summary = read_json_file(base.get("summary_file"))
    serialized_summary = serialize_summary(raw_summary, job) if raw_summary else {}
    latest_image_items = _image_items_from_paths(base.get("latest_images"), job)
    if not latest_image_items:
        latest_image_items = artifact_items

    input_image_urls = []
    for item in base.get("input_images", []):
        if not isinstance(item, dict):
            continue
        url = path_to_pipeline_file_url(item.get("saved_path"), job)
        if url:
            input_image_urls.append(url)

    return {
        **base,
        "job_id": job["id"],
        "run_id": base.get("run_id") or job["id"],
        "task_key": base.get("task_key") or job["task_type"],
        "title": base.get("title") or job["title"],
        "status": base.get("status") or job["status"],
        "created_at": base.get("created_at") or job["created_at"],
        "updated_at": job["updated_at"],
        "latest_image_urls": [item["url"] for item in latest_image_items],
        "latest_thumbnail_urls": [
            item["thumbnail_url"] for item in latest_image_items
        ],
        "latest_image_items": latest_image_items,
        "input_image_urls": input_image_urls,
        "summary": serialized_summary,
        "summary_file_url": path_to_pipeline_file_url(base.get("summary_file"), job),
        "debug_log_file_url": path_to_pipeline_file_url(base.get("debug_log_file"), job),
        "download_url": f"/api/runs/{base.get('run_id') or job['id']}/download",
        "open_url": f"/api/runs/{base.get('run_id') or job['id']}/open",
    }


def serialize_job(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
    record = result.get("record") if isinstance(result.get("record"), dict) else None
    raw_summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    if not raw_summary and isinstance(record, dict):
        raw_summary = read_json_file(record.get("summary_file"))

    serialized_summary = serialize_summary(raw_summary, job) if raw_summary else {}
    serialized_record = serialize_record(job, record, artifacts)
    if serialized_record and serialized_record.get("summary") and not serialized_summary:
        serialized_summary = serialized_record["summary"]
    if result.get("message") and not serialized_summary.get("message"):
        serialized_summary = {**serialized_summary, "message": result.get("message")}
    serialized_summary = {**serialized_summary, "artifacts": artifacts}

    payload = {
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
        "summary": serialized_summary,
    }
    if serialized_record:
        payload["record"] = serialized_record
    return payload


def _event_lines(events: list[dict[str, Any]]) -> list[str]:
    return [
        f"[{format_china_time(item.get('created_at', ''))}] [{item.get('level', 'info')}] {item.get('message', '')}"
        for item in events
    ]


def _json_text(value: Any) -> Any:
    try:
        return json.loads(str(value or "{}"))
    except Exception:
        return {}


def _client_log_lines(items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in items:
        details = _json_text(item.get("details_json"))
        suffix = f" {json.dumps(details, ensure_ascii=False)}" if details else ""
        lines.append(
            f"[{format_china_time(item.get('created_at', ''))}] [{item.get('level', 'error')}] "
            f"{item.get('message', '')}{suffix}"
        )
    return lines


def _audit_log_lines(items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in items:
        details = _json_text(item.get("details_json"))
        suffix = f" {json.dumps(details, ensure_ascii=False)}" if details else ""
        lines.append(
            f"[{format_china_time(item.get('created_at', ''))}] [audit] {item.get('action', '')} "
            f"{item.get('target_type', '')}:{item.get('target_id', '')} "
            f"actor={item.get('actor_id') or ''}{suffix}"
        )
    return lines


def collect_global_log_entries(
    *,
    user_id: str | None,
    limit: int = USER_LOG_LINE_LIMIT,
    include_audit: bool = False,
) -> dict[str, Any]:
    safe_limit = max(1, int(limit or USER_LOG_LINE_LIMIT))
    entries = [
        {
            "key": "total",
            "label": "总日志",
            "path": "database:job_events",
            "content": limit_text_lines(
                "\n".join(
                    _event_lines(list_recent_job_events(user_id=user_id, limit=safe_limit))
                ).strip(),
                max_lines=safe_limit,
            ),
        },
        {
            "key": "client",
            "label": "前端错误日志",
            "path": "database:client_logs",
            "content": limit_text_lines(
                "\n".join(
                    _client_log_lines(
                        list_recent_client_logs(user_id=user_id, limit=safe_limit)
                    )
                ).strip(),
                max_lines=safe_limit,
            ),
        },
    ]
    if include_audit:
        entries.append(
            {
                "key": "audit",
                "label": "管理操作日志",
                "path": "database:audit_logs",
                "content": limit_text_lines(
                    "\n".join(
                        _audit_log_lines(list_recent_audit_logs(limit=safe_limit))
                    ).strip(),
                    max_lines=safe_limit,
                ),
            }
        )
    return {"entries": entries, "selected_key": "total", "scope": "global"}


def collect_job_log_entries(
    job: dict[str, Any],
    *,
    max_lines: int | None = USER_LOG_LINE_LIMIT,
) -> dict[str, Any]:
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    record = result.get("record") if isinstance(result.get("record"), dict) else {}
    job_dir = job_storage_dir(job["user_id"], job["id"])
    pipeline_logs_dir = job_dir / "pipeline" / "logs"
    entries: list[dict[str, Any]] = []

    debug_log_file = record.get("debug_log_file")
    if debug_log_file:
        entries.append(
            {
                "key": "run",
                "label": "当前任务日志",
                "path": str(debug_log_file),
                "content": read_text_tail(debug_log_file, max_lines=max_lines),
            }
        )

    events = list_job_events(job["id"], user_id=job["user_id"])
    event_lines = _event_lines(events)
    if job.get("error") and not any(str(job["error"]) in line for line in event_lines):
        event_lines.append(f"[error] {job['error']}")
    entries.append(
        {
            "key": "events",
            "label": "平台任务事件",
            "path": "database:job_events",
            "content": limit_text_lines("\n".join(event_lines).strip(), max_lines=max_lines),
        }
    )

    app_log_path = pipeline_logs_dir / "app.log"
    entries.append(
        {
            "key": "app",
            "label": "Pipeline 应用日志",
            "path": str(app_log_path),
            "content": read_text_tail(app_log_path, max_lines=max_lines),
        }
    )

    backend_log_path = pipeline_logs_dir / "backend-server.log"
    if backend_log_path.exists():
        entries.append(
            {
                "key": "backend",
                "label": "后端服务日志",
                "path": str(backend_log_path),
                "content": read_text_tail(backend_log_path, max_lines=max_lines),
            }
        )

    selected_key = "run" if entries and entries[0]["key"] == "run" else entries[0]["key"]
    return {"entries": entries, "selected_key": selected_key, "scope": "job"}
