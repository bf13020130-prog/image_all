#!/usr/bin/env python3
from __future__ import annotations

import json
import base64
import io
import logging
import mimetypes
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import app as pipeline_app


APP_TITLE = "设计出图"
TASK_KEY_STYLE_REPLICATE = "style-replicate"
TASK_KEY_STYLE_REPLICATE_V2 = "style-replicate-v2"
TASK_KEY_IMAGE_EDIT = "image-edit"
TASK_KEY_IMAGE_AGENT = "image-agent"
TASK_KEY_COLOR_MATCH = "color-match"
LOCAL_CORS_ORIGIN_REGEX = r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$"


@dataclass
class ProjectPaths:
    project_root: Path
    asset_root: Path
    web_dir: Path
    temp_upload_dir: Path


@dataclass
class JobState:
    job_id: str
    task_key: str
    title: str
    status: str = "queued"
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    error_detail: dict[str, Any] | None = None
    record: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_log(self, line: str) -> None:
        with self._lock:
            self.logs.append(line)
            if len(self.logs) > 600:
                self.logs = self.logs[-600:]
            self.updated_at = datetime.now().isoformat(timespec="seconds")

    def mark_running(self) -> None:
        with self._lock:
            self.status = "running"
            self.updated_at = datetime.now().isoformat(timespec="seconds")

    def mark_completed(self, record: dict[str, Any], summary: dict[str, Any]) -> None:
        with self._lock:
            self.status = "completed"
            self.record = record
            self.summary = summary
            self.error = None
            self.updated_at = datetime.now().isoformat(timespec="seconds")

    def mark_progress(self, summary: dict[str, Any]) -> None:
        with self._lock:
            self.summary = summary
            self.updated_at = datetime.now().isoformat(timespec="seconds")

    def mark_partial(
        self,
        record: dict[str, Any],
        summary: dict[str, Any],
        error: str,
        error_detail: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self.status = "partial"
            self.record = record
            self.summary = summary
            self.error = error
            self.error_detail = error_detail
            self.updated_at = datetime.now().isoformat(timespec="seconds")

    def mark_failed(
        self,
        error: str,
        error_detail: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self.status = "failed"
            self.error = error
            self.error_detail = error_detail
            self.updated_at = datetime.now().isoformat(timespec="seconds")


class JobManager:
    def __init__(self, context: pipeline_app.AppContext) -> None:
        self.context = context
        self.executor = ThreadPoolExecutor(
            max_workers=pipeline_app.MAX_IMAGE_CONCURRENCY,
            thread_name_prefix="design-output",
        )
        self.jobs: dict[str, JobState] = {}
        self._lock = threading.Lock()

    def create_style_replicate_job(
        self,
        *,
        settings: pipeline_app.Settings,
        options: pipeline_app.RunOptions,
        metadata: dict[str, Any],
        cleanup_dir: Path | None = None,
    ) -> JobState:
        job = JobState(
            job_id=uuid.uuid4().hex[:12],
            task_key=TASK_KEY_STYLE_REPLICATE,
            title="复刻风格图片",
            metadata=metadata,
        )
        with self._lock:
            self.jobs[job.job_id] = job
        self.executor.submit(self._run_job, job, settings, options, cleanup_dir)
        return job

    def create_style_replicate2_job(
        self,
        *,
        settings: pipeline_app.Settings,
        options: pipeline_app.StyleReplicate2Options,
        metadata: dict[str, Any],
        cleanup_dir: Path | None = None,
    ) -> JobState:
        job = JobState(
            job_id=uuid.uuid4().hex[:12],
            task_key=TASK_KEY_STYLE_REPLICATE_V2,
            title="复刻风格图片2",
            metadata=metadata,
        )
        with self._lock:
            self.jobs[job.job_id] = job
        self.executor.submit(
            self._run_style_replicate2_job,
            job,
            settings,
            options,
            cleanup_dir,
        )
        return job

    def create_image_edit_job(
        self,
        *,
        settings: pipeline_app.Settings,
        options: pipeline_app.ImageEditOptions,
        metadata: dict[str, Any],
        cleanup_dir: Path | None = None,
    ) -> JobState:
        job = JobState(
            job_id=uuid.uuid4().hex[:12],
            task_key=TASK_KEY_IMAGE_EDIT,
            title="图片生成",
            metadata=metadata,
        )
        with self._lock:
            self.jobs[job.job_id] = job
        self.executor.submit(self._run_image_edit_job, job, settings, options, cleanup_dir)
        return job

    def create_image_agent_job(
        self,
        *,
        settings: pipeline_app.Settings,
        options: pipeline_app.ImageAgentOptions,
        metadata: dict[str, Any],
        cleanup_dir: Path | None = None,
    ) -> JobState:
        job = JobState(
            job_id=uuid.uuid4().hex[:12],
            task_key=TASK_KEY_IMAGE_AGENT,
            title="图片生成 Agent",
            metadata=metadata,
        )
        with self._lock:
            self.jobs[job.job_id] = job
        self.executor.submit(self._run_image_agent_job, job, settings, options, cleanup_dir)
        return job

    def create_color_match_job(
        self,
        *,
        settings: pipeline_app.Settings,
        options: pipeline_app.ColorMatchOptions,
        metadata: dict[str, Any],
        cleanup_dir: Path | None = None,
    ) -> JobState:
        job = JobState(
            job_id=uuid.uuid4().hex[:12],
            task_key=TASK_KEY_COLOR_MATCH,
            title="一键追色",
            metadata=metadata,
        )
        with self._lock:
            self.jobs[job.job_id] = job
        self.executor.submit(self._run_color_match_job, job, settings, options, cleanup_dir)
        return job

    def _run_job(
        self,
        job: JobState,
        settings: pipeline_app.Settings,
        options: pipeline_app.RunOptions,
        cleanup_dir: Path | None,
    ) -> None:
        job.mark_running()
        logger = pipeline_app.AppLogger(
            self.context.app_log_path,
            ui_callback=job.add_log,
        )
        try:
            record = pipeline_app.run_pipeline(self.context, settings, options, logger)
            summary = read_json_file(Path(record.get("summary_file", "")), {})
            job.mark_completed(record, summary)
        except Exception as exc:
            job.mark_failed(str(exc), error_payload(exc))
        finally:
            if cleanup_dir is not None:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    def _run_style_replicate2_job(
        self,
        job: JobState,
        settings: pipeline_app.Settings,
        options: pipeline_app.StyleReplicate2Options,
        cleanup_dir: Path | None,
    ) -> None:
        job.mark_running()
        logger = pipeline_app.AppLogger(
            self.context.app_log_path,
            ui_callback=job.add_log,
        )
        try:
            record = pipeline_app.run_style_replicate2_pipeline(
                self.context,
                settings,
                options,
                logger,
            )
            summary = read_json_file(Path(record.get("summary_file", "")), {})
            job.mark_completed(record, summary)
        except Exception as exc:
            job.mark_failed(str(exc), error_payload(exc))
        finally:
            if cleanup_dir is not None:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    def _run_image_edit_job(
        self,
        job: JobState,
        settings: pipeline_app.Settings,
        options: pipeline_app.ImageEditOptions,
        cleanup_dir: Path | None,
    ) -> None:
        job.mark_running()
        logger = pipeline_app.AppLogger(
            self.context.app_log_path,
            ui_callback=job.add_log,
        )
        try:
            record = pipeline_app.run_image_edit_pipeline(
                self.context,
                settings,
                options,
                logger,
                progress_callback=job.mark_progress,
            )
            summary = read_json_file(Path(record.get("summary_file", "")), {})
            if record.get("status") == "partial":
                error = str(
                    summary.get("error")
                    or record.get("error")
                    or "部分生成失败，已保留成功结果。"
                )
                job.mark_partial(record, summary, error, error_payload(error))
            else:
                job.mark_completed(record, summary)
        except Exception as exc:
            job.mark_failed(str(exc), error_payload(exc))
        finally:
            if cleanup_dir is not None:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    def _run_image_agent_job(
        self,
        job: JobState,
        settings: pipeline_app.Settings,
        options: pipeline_app.ImageAgentOptions,
        cleanup_dir: Path | None,
    ) -> None:
        job.mark_running()
        logger = pipeline_app.AppLogger(
            self.context.app_log_path,
            ui_callback=job.add_log,
        )
        try:
            record = pipeline_app.run_image_agent_pipeline(
                self.context,
                settings,
                options,
                logger,
                progress_callback=job.mark_progress,
            )
            summary = read_json_file(Path(record.get("summary_file", "")), {})
            job.mark_completed(record, summary)
        except Exception as exc:
            job.mark_failed(str(exc), error_payload(exc))
        finally:
            if cleanup_dir is not None:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    def _run_color_match_job(
        self,
        job: JobState,
        settings: pipeline_app.Settings,
        options: pipeline_app.ColorMatchOptions,
        cleanup_dir: Path | None,
    ) -> None:
        job.mark_running()
        logger = pipeline_app.AppLogger(
            self.context.app_log_path,
            ui_callback=job.add_log,
        )
        try:
            record = pipeline_app.run_color_match_pipeline(
                self.context,
                settings,
                options,
                logger,
            )
            summary = read_json_file(Path(record.get("summary_file", "")), {})
            job.mark_completed(record, summary)
        except Exception as exc:
            job.mark_failed(str(exc), error_payload(exc))
        finally:
            if cleanup_dir is not None:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    def list_jobs(self) -> list[JobState]:
        with self._lock:
            jobs = list(self.jobs.values())
        jobs.sort(key=lambda item: item.created_at, reverse=True)
        return jobs

    def get_job(self, job_id: str) -> JobState | None:
        with self._lock:
            return self.jobs.get(job_id)

    def remove_run(self, run_id: str) -> None:
        target_run_id = str(run_id or "").strip()
        if not target_run_id:
            return
        with self._lock:
            self.jobs = {
                job_id: job
                for job_id, job in self.jobs.items()
                if not (
                    isinstance(job.record, dict)
                    and job.record.get("run_id") == target_run_id
                )
                and not (
                    isinstance(job.summary, dict)
                    and job.summary.get("run_id") == target_run_id
                )
            }


def resolve_config_template_path(asset_root: Path) -> Path:
    candidates = (
        asset_root / "seed-config.json",
        asset_root / "config.example.json",
        asset_root / "backend" / "config.example.json",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def create_context(project_root: Path, asset_root: Path | None = None) -> pipeline_app.AppContext:
    asset_root = asset_root or project_root
    return pipeline_app.AppContext(
        root_dir=project_root,
        data_dir=project_root / "data",
        logs_dir=project_root / "logs",
        config_path=project_root / "config.json",
        config_example_path=resolve_config_template_path(asset_root),
        history_path=project_root / "data" / "history.json",
        edit_conversations_path=project_root / "data" / "edit_conversations.json",
        app_log_path=project_root / "logs" / "app.log",
    )


def read_json_file(path: Path, default: Any) -> Any:
    if not path or not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def read_text_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


ERROR_RULES = (
    (
        "CONFIG_MISSING_LLM_KEY",
        "config",
        (("大模型 api key", "llm api key", "有效的大模型"),),
        "打开设置页，填写大模型 API Key 后重试。",
        False,
    ),
    (
        "CONFIG_MISSING_GEMINI_IMAGE_KEY",
        "config",
        ("gemini", "api key"),
        "打开设置页，填写 Gemini API Key，或切换到已配置密钥的生图模型。",
        False,
    ),
    (
        "CONFIG_MISSING_GPT_IMAGE_KEY",
        "config",
        ("gpt-image", "api key"),
        "打开设置页，填写 gpt-image-2 API Key 或 1K 密钥后重试。",
        False,
    ),
    (
        "CONFIG_MISSING_IMAGE_KEY",
        "config",
        (("当前生图模型对应的 api key", "生图 api key"),),
        "打开设置页，填写当前生图模型对应的 API Key 后重试。",
        False,
    ),
    (
        "VALIDATION_TOO_MANY_IMAGES",
        "validation",
        ("最多支持", "张"),
        "减少上传或链接图片数量后重试。",
        False,
    ),
    (
        "VALIDATION_UNSUPPORTED_OUTPUT",
        "validation",
        (("不支持比例", "不支持的画幅比例", "不支持的分辨率", "auto 比例", "必须选择具体比例"),),
        "换一个当前模型支持的分辨率和比例后重试。",
        False,
    ),
    (
        "PROVIDER_TIMEOUT",
        "provider",
        (("timed out", "timeout", "超时"),),
        "外部接口响应超时，可稍后重试；如果图片较大，可以提高读取超时。",
        True,
    ),
    (
        "PROVIDER_HTTP_ERROR",
        "provider",
        (("http ", "failed with http"),),
        "外部接口返回错误，打开日志查看请求和响应详情。",
        True,
    ),
    (
        "PROVIDER_NO_IMAGE_PAYLOAD",
        "provider",
        (("没有解析出有效图片", "没有解析出图片 payload", "没有返回可用图片"),),
        "外部生图接口没有返回可保存的图片，打开日志查看原始响应。",
        True,
    ),
    (
        "AGENT_PLAN_PARSE_FAILED",
        "agent",
        (("agent 规划阶段", "write_plan"),),
        "Agent 规划结果不可解析，可调整 Agent 规划提示词后重试。",
        True,
    ),
    (
        "AGENT_DESIGN_PARSE_FAILED",
        "agent",
        (("agent 创作", "生图提示词", "工具任务"),),
        "Agent 创作结果不可解析，可调整 Agent 创作提示词后重试。",
        True,
    ),
    (
        "FILE_NOT_FOUND",
        "file",
        (("不存在", "not found"),),
        "确认文件仍在原位置，或重新上传图片后重试。",
        False,
    ),
)


def error_markers_match(
    markers: tuple[str | tuple[str, ...], ...],
    text: str,
) -> bool:
    for marker in markers:
        if isinstance(marker, tuple):
            if not any(option.lower() in text for option in marker):
                return False
            continue
        if marker.lower() not in text:
            return False
    return True


def error_payload(error: Any) -> dict[str, Any]:
    message = str(error or "请求失败。")
    lowered = message.lower()
    payload = {
        "error": message,
        "code": "UNKNOWN_ERROR",
        "category": "unknown",
        "hint": "打开日志查看详情后重试。",
        "retryable": False,
    }
    for code, category, markers, hint, retryable in ERROR_RULES:
        if error_markers_match(markers, lowered):
            payload.update(
                {
                    "code": code,
                    "category": category,
                    "hint": hint,
                    "retryable": retryable,
                }
            )
            break
    return payload


def build_pages() -> list[dict[str, Any]]:
    return [
        {"key": TASK_KEY_STYLE_REPLICATE, "label": "复刻风格图片"},
        {"key": TASK_KEY_STYLE_REPLICATE_V2, "label": "复刻风格图片2"},
        {"key": TASK_KEY_IMAGE_EDIT, "label": "图片生成"},
        {"key": TASK_KEY_COLOR_MATCH, "label": "一键追色"},
        {"key": "history", "label": "历史"},
        {"key": "settings", "label": "设置"},
    ]


def validate_settings(settings: pipeline_app.Settings) -> pipeline_app.Settings:
    settings.image_agent_endpoint_type = pipeline_app.normalize_llm_endpoint_type(
        settings.image_agent_endpoint_type
    )
    if settings.llm_connect_timeout_seconds <= 0:
        raise HTTPException(status_code=400, detail="大模型连接超时必须大于 0。")
    if settings.image_connect_timeout_seconds <= 0:
        raise HTTPException(status_code=400, detail="生图连接超时必须大于 0。")
    if settings.default_prompt_count <= 0:
        raise HTTPException(status_code=400, detail="默认提示词数必须大于 0。")
    if settings.default_images_per_prompt <= 0:
        raise HTTPException(status_code=400, detail="默认生成次数必须大于 0。")
    if settings.default_concurrency <= 0:
        raise HTTPException(status_code=400, detail="共享并发池必须大于 0。")
    try:
        (
            settings.default_output_resolution,
            settings.default_output_aspect_ratio,
        ) = pipeline_app.parse_output_selection(
            output_resolution=settings.default_output_resolution,
            output_aspect_ratio=settings.default_output_aspect_ratio,
            legacy_output=settings.default_aspect_ratio,
        )
    except pipeline_app.AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    settings.default_aspect_ratio = pipeline_app.output_selection_to_legacy_value(
        settings.default_output_resolution,
        settings.default_output_aspect_ratio,
    )
    if settings.default_concurrency > pipeline_app.MAX_IMAGE_CONCURRENCY:
        raise HTTPException(
            status_code=400,
            detail=f"共享并发池不能超过 {pipeline_app.MAX_IMAGE_CONCURRENCY}。",
        )
    return settings


def settings_payload(settings: pipeline_app.Settings) -> dict[str, Any]:
    settings.image_agent_endpoint_type = pipeline_app.normalize_llm_endpoint_type(
        settings.image_agent_endpoint_type
    )
    return {
        **settings.to_public_dict(),
        "available_llm_endpoint_types": [
            {"value": pipeline_app.LLM_ENDPOINT_CHAT_COMPLETIONS, "label": "/v1/chat/completions"},
            {"value": pipeline_app.LLM_ENDPOINT_RESPONSES, "label": "/v1/responses"},
        ],
        "available_image_models": pipeline_app.image_model_choices(),
        "available_output_presets": pipeline_app.output_preset_choices(),
        "available_output_resolutions": pipeline_app.output_resolution_choices(),
        "available_output_aspect_ratios": pipeline_app.output_aspect_ratio_choices(),
        "limits": {
            "style_reference_max": pipeline_app.MAX_STYLE_REFERENCE_IMAGES,
            "product_reference_max": pipeline_app.MAX_PRODUCT_REFERENCE_IMAGES,
            "style_replicate2_reference_max": pipeline_app.MAX_STYLE_REPLICATE2_REFERENCE_IMAGES,
            "image_edit_input_max": pipeline_app.MAX_IMAGE_EDIT_INPUT_IMAGES,
            "agent_image_count_max": pipeline_app.MAX_IMAGE_AGENT_REQUEST_COUNT,
        },
        "image_model_capabilities": {
            model["value"]: {
                "allowed_resolutions": pipeline_app.image_agent_allowed_resolutions(
                    model["value"]
                ),
                "allowed_aspect_ratios": pipeline_app.image_agent_allowed_aspect_ratios(
                    model["value"]
                ),
                "requires_fixed_output": pipeline_app.is_nano_banana_model(
                    model["value"]
                ),
            }
            for model in pipeline_app.image_model_choices()
        },
        "max_shared_concurrency": pipeline_app.MAX_IMAGE_CONCURRENCY,
        "app_title": APP_TITLE,
    }


SECRET_SETTING_KEYS = (
    "llm_api_key",
    "color_match_api_key",
    "image_agent_api_key",
    "image_api_key",
    "image_1k_api_key",
    "gpt_image_api_key",
    "gpt_image_1k_api_key",
    "gemini_image_api_key",
)


def merge_preserved_secret_settings(
    payload: dict[str, Any],
    current_settings: pipeline_app.Settings,
) -> dict[str, Any]:
    merged = dict(payload or {})
    current_values = current_settings.to_dict()
    for key in SECRET_SETTING_KEYS:
        current_value = str(current_values.get(key, ""))
        incoming_value = str(merged.get(key, "")).strip()
        if current_value and incoming_value == pipeline_app.mask_secret(current_value):
            merged[key] = current_value
    return merged


def path_to_data_url(
    path: str | Path | None,
    context: pipeline_app.AppContext,
) -> str | None:
    if not path:
        return None
    resolved = Path(path).expanduser().resolve()
    try:
        relative = resolved.relative_to(context.data_dir.resolve())
    except Exception:
        return None
    return f"/data/{quote(relative.as_posix())}"


def path_to_thumbnail_api_url(
    path: str | Path | None,
    context: pipeline_app.AppContext,
) -> str | None:
    if not path:
        return None
    resolved = Path(path).expanduser().resolve()
    try:
        relative = resolved.relative_to(context.data_dir.resolve())
    except Exception:
        return None
    return f"/api/thumbnails/{quote(relative.as_posix())}"


def image_thumbnail_url(
    path: str | Path | None,
    context: pipeline_app.AppContext,
    *,
    create_missing: bool = False,
) -> str | None:
    if not path:
        return None
    try:
        source = Path(path).expanduser().resolve()
        thumbnail_path = pipeline_app.thumbnail_path_for_image(source)
        if not thumbnail_path.exists() and create_missing:
            created_path = pipeline_app.create_image_thumbnail(source)
            thumbnail_path = Path(created_path) if created_path else thumbnail_path
    except Exception:
        return None
    if thumbnail_path.exists():
        return path_to_data_url(thumbnail_path, context)
    return path_to_thumbnail_api_url(source, context)


def image_url_pair(
    path: str | Path | None,
    context: pipeline_app.AppContext,
    *,
    create_missing_thumbnail: bool = False,
) -> dict[str, str] | None:
    original_url = path_to_data_url(path, context)
    if not original_url:
        return None
    return {
        "url": original_url,
        "thumbnail_url": image_thumbnail_url(
            path,
            context,
            create_missing=create_missing_thumbnail,
        )
        or original_url,
    }


def serialize_summary(
    summary: dict[str, Any],
    context: pipeline_app.AppContext,
) -> dict[str, Any]:
    if not summary:
        return {}

    renders: list[dict[str, Any]] = []
    for item in summary.get("renders", []):
        image_paths = item.get("images", [])
        image_details = item.get("image_details", [])
        detail_thumbnail_paths: dict[str, str] = {}
        if isinstance(image_details, list):
            for detail in image_details:
                if not isinstance(detail, dict):
                    continue
                image_path = str(detail.get("path") or "")
                thumbnail_path = str(detail.get("thumbnail_path") or "")
                if image_path and thumbnail_path:
                    detail_thumbnail_paths[image_path] = thumbnail_path
        image_items: list[dict[str, str]] = []
        for image_path in image_paths:
            if not isinstance(image_path, str):
                continue
            pair = image_url_pair(
                image_path,
                context,
                create_missing_thumbnail=False,
            )
            if not pair:
                continue
            detail_thumbnail_url = path_to_data_url(
                detail_thumbnail_paths.get(image_path),
                context,
            )
            if detail_thumbnail_url:
                pair["thumbnail_url"] = detail_thumbnail_url
            image_items.append(pair)
        renders.append(
            {
                **item,
                "response_file_url": path_to_data_url(item.get("response_file"), context),
                "image_urls": [item["url"] for item in image_items],
                "thumbnail_urls": [item["thumbnail_url"] for item in image_items],
                "image_items": image_items,
            }
        )

    prompts_text = ""
    prompts_file = summary.get("prompts_file")
    if prompts_file:
        prompts_text = read_text_file(Path(prompts_file))

    def image_urls_from_paths(paths: Any) -> list[str]:
        if not isinstance(paths, list):
            return []
        return [
            url
            for url in (
                path_to_data_url(image_path, context)
                for image_path in paths
                if isinstance(image_path, str)
            )
            if url
        ]

    def image_items_from_paths(paths: Any) -> list[dict[str, str]]:
        if not isinstance(paths, list):
            return []
        return [
            item
            for item in (
                image_url_pair(image_path, context, create_missing_thumbnail=False)
                for image_path in paths
                if isinstance(image_path, str)
            )
            if item
        ]

    color_match_outputs = summary.get("color_match_outputs")
    serialized_color_match_outputs: dict[str, Any] | None = None
    if isinstance(color_match_outputs, dict):
        serialized_color_match_outputs = {}
        for key, value in color_match_outputs.items():
            if isinstance(value, dict):
                output_image_items = image_items_from_paths(value.get("images"))
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

    return {
        **summary,
        "prompts_file_url": path_to_data_url(summary.get("prompts_file"), context),
        "prompt_request_file_url": path_to_data_url(
            summary.get("prompt_request_file"),
            context,
        ),
        "prompt_response_file_url": path_to_data_url(
            summary.get("prompt_response_file"),
            context,
        ),
        "render_manifest_file_url": path_to_data_url(
            summary.get("render_manifest_file"),
            context,
        ),
        "debug_log_file_url": path_to_data_url(summary.get("debug_log_file"), context),
        "color_analysis_file_url": path_to_data_url(
            summary.get("color_analysis_file"),
            context,
        ),
        "desaturated_scene_url": path_to_data_url(
            summary.get("desaturated_scene"),
            context,
        ),
        "desaturated_scene_thumbnail_url": path_to_data_url(
            summary.get("desaturated_scene_thumbnail"),
            context,
        )
        or image_thumbnail_url(summary.get("desaturated_scene"), context),
        "color_match_outputs": serialized_color_match_outputs,
        "renders": renders,
        "prompts_text": prompts_text,
    }


def serialize_record(
    record: dict[str, Any],
    context: pipeline_app.AppContext,
) -> dict[str, Any]:
    summary = read_json_file(Path(record.get("summary_file", "")), {})
    serialized_summary = serialize_summary(summary, context) if summary else {}
    latest_image_items = [
        item
        for item in (
            image_url_pair(image_path, context, create_missing_thumbnail=False)
            for image_path in record.get("latest_images", [])
        )
        if item
    ]
    input_image_urls = [
        url
        for url in (
            path_to_data_url(
                item.get("saved_path") if isinstance(item, dict) else None,
                context,
            )
            for item in record.get("input_images", [])
        )
        if url
    ]
    return {
        **record,
        "latest_image_urls": [item["url"] for item in latest_image_items],
        "latest_thumbnail_urls": [
            item["thumbnail_url"] for item in latest_image_items
        ],
        "latest_image_items": latest_image_items,
        "input_image_urls": input_image_urls,
        "summary": serialized_summary,
        "summary_file_url": path_to_data_url(record.get("summary_file"), context),
        "debug_log_file_url": path_to_data_url(record.get("debug_log_file"), context),
        "download_url": f"/api/runs/{record.get('run_id')}/download",
        "open_url": f"/api/runs/{record.get('run_id')}/open",
    }


def serialize_job(job: JobState, context: pipeline_app.AppContext) -> dict[str, Any]:
    payload = {
        "job_id": job.job_id,
        "task_key": job.task_key,
        "title": job.title,
        "status": job.status,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "logs": list(job.logs),
        "error": job.error,
        "error_detail": job.error_detail,
        "metadata": job.metadata,
    }
    if job.record:
        payload["record"] = serialize_record(job.record, context)
    if job.summary:
        payload["summary"] = serialize_summary(job.summary, context)
    return payload


def image_bytes_to_payload(
    *,
    data: bytes,
    name: str,
    mime_type: str,
) -> dict[str, str]:
    encoded = base64.b64encode(data).decode("ascii")
    return {
        "name": name,
        "mime_type": mime_type,
        "data_url": f"data:{mime_type};base64,{encoded}",
    }


def collect_clipboard_images(limit: int = 16) -> list[dict[str, str]]:
    try:
        from PIL import Image, ImageGrab
    except Exception as exc:  # pragma: no cover - depends on packaged runtime.
        raise RuntimeError("当前运行环境缺少 Pillow，无法读取系统剪贴板图片。") from exc

    grabbed = ImageGrab.grabclipboard()
    if grabbed is None:
        return []

    if isinstance(grabbed, Image.Image):
        buffer = io.BytesIO()
        grabbed.save(buffer, format="PNG")
        return [
            image_bytes_to_payload(
                data=buffer.getvalue(),
                name=f"clipboard-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png",
                mime_type="image/png",
            )
        ]

    if isinstance(grabbed, list):
        items: list[dict[str, str]] = []
        for raw_path in grabbed[:limit]:
            path = Path(str(raw_path)).expanduser()
            if not path.is_file():
                continue
            mime_type = mimetypes.guess_type(path.name)[0] or ""
            if not mime_type.startswith("image/"):
                continue
            items.append(
                image_bytes_to_payload(
                    data=path.read_bytes(),
                    name=path.name,
                    mime_type=mime_type,
                )
            )
        return items

    return []


def find_record_by_run_id(
    context: pipeline_app.AppContext,
    run_id: str,
) -> dict[str, Any] | None:
    for record in context.load_history():
        if record.get("run_id") == run_id:
            return record
    return None


def delete_record_by_run_id(
    context: pipeline_app.AppContext,
    run_id: str,
) -> dict[str, Any] | None:
    target_run_id = str(run_id or "").strip()
    if not target_run_id:
        return None
    history = context.load_history()
    removed: dict[str, Any] | None = None
    remaining: list[dict[str, Any]] = []
    for record in history:
        if record.get("run_id") == target_run_id and removed is None:
            removed = record
            continue
        remaining.append(record)
    if removed is None:
        return None
    context.save_history(remaining)
    run_dir = removed.get("run_dir")
    if isinstance(run_dir, str) and run_dir.strip():
        pipeline_app.cleanup_failed_run_dir(context, Path(run_dir))
    return removed


def edit_conversation_run_ids(conversation: dict[str, Any]) -> list[str]:
    run_ids: list[str] = []
    messages = conversation.get("messages")
    if not isinstance(messages, list):
        return run_ids
    for message in messages:
        if not isinstance(message, dict):
            continue
        for key in ("runId", "run_id"):
            run_id = str(message.get(key) or "").strip()
            if run_id and run_id not in run_ids:
                run_ids.append(run_id)
    return run_ids


def delete_edit_conversation(
    context: pipeline_app.AppContext,
    conversation_id: str,
) -> dict[str, Any] | None:
    target_id = str(conversation_id or "").strip()
    if not target_id:
        return None
    conversations = context.load_edit_conversations()
    removed_conversation: dict[str, Any] | None = None
    remaining: list[dict[str, Any]] = []
    for item in conversations:
        if (
            removed_conversation is None
            and str(item.get("id") or "").strip() == target_id
        ):
            removed_conversation = item
            continue
        remaining.append(item)

    deleted_run_ids = (
        edit_conversation_run_ids(removed_conversation)
        if removed_conversation is not None
        else []
    )
    deleted_run_id_set = set(deleted_run_ids)
    history = context.load_history()
    removed_records: list[dict[str, Any]] = []
    remaining_history: list[dict[str, Any]] = []
    for record in history:
        run_id = str(record.get("run_id") or "").strip()
        record_conversation_id = str(record.get("conversation_id") or "").strip()
        should_remove = (
            (run_id and run_id in deleted_run_id_set)
            or record_conversation_id == target_id
        )
        if should_remove:
            removed_records.append(record)
            if run_id and run_id not in deleted_run_id_set:
                deleted_run_ids.append(run_id)
                deleted_run_id_set.add(run_id)
            continue
        remaining_history.append(record)

    if removed_records:
        context.save_history(remaining_history)
        for record in removed_records:
            run_dir = record.get("run_dir")
            if isinstance(run_dir, str) and run_dir.strip():
                pipeline_app.cleanup_failed_run_dir(context, Path(run_dir))

    if removed_conversation is None and not removed_records:
        return None
    if removed_conversation is not None:
        context.save_edit_conversations(remaining)

    return {
        "conversation_id": target_id,
        "deleted_run_ids": deleted_run_ids,
        "deleted_history_count": len(removed_records),
    }


def find_active_summary_by_run_id(
    job_manager: JobManager,
    run_id: str,
) -> dict[str, Any] | None:
    for job in job_manager.list_jobs():
        for candidate in (job.summary, job.record):
            if isinstance(candidate, dict) and candidate.get("run_id") == run_id:
                return candidate
    return None


def resolve_run_open_path(record: dict[str, Any]) -> Path:
    latest_images = record.get("latest_images") or []
    for image_path in latest_images:
        candidate = Path(image_path).expanduser().resolve().parent
        if candidate.exists():
            return candidate
    for render in record.get("renders") or []:
        if not isinstance(render, dict):
            continue
        for image_path in render.get("images") or []:
            if not isinstance(image_path, str):
                continue
            candidate = Path(image_path).expanduser().resolve().parent
            if candidate.exists():
                return candidate

    run_dir = Path(record.get("run_dir", "")).expanduser().resolve()
    for candidate in (run_dir / "images", run_dir / "renders", run_dir):
        if candidate.exists():
            return candidate
    return run_dir


def resolve_log_record(
    *,
    context: pipeline_app.AppContext,
    job_manager: JobManager,
    job_id: str | None,
    run_id: str | None,
) -> dict[str, Any] | None:
    if job_id:
        job = job_manager.get_job(job_id)
        if job and job.record:
            return job.record
    if run_id:
        return find_record_by_run_id(context, run_id)
    history = context.load_history()
    return history[0] if history else None


def collect_log_entries(
    context: pipeline_app.AppContext,
    record: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    entries = [
        {
            "key": "app",
            "label": "应用日志",
            "path": str(context.app_log_path),
            "content": read_text_file(context.app_log_path),
        },
        {
            "key": "backend",
            "label": "后端服务日志",
            "path": str(context.logs_dir / "backend-server.log"),
            "content": read_text_file(context.logs_dir / "backend-server.log"),
        },
        {
            "key": "shell",
            "label": "桌面壳日志",
            "path": str(context.logs_dir / "electron-shell.log"),
            "content": read_text_file(context.logs_dir / "electron-shell.log"),
        },
    ]

    if record and record.get("debug_log_file"):
        debug_path = Path(record["debug_log_file"])
        entries.insert(
            0,
            {
                "key": "run",
                "label": "当前任务日志",
                "path": str(debug_path),
                "content": read_text_file(debug_path),
            },
        )
    return entries


def resolve_log_source(
    *,
    context: pipeline_app.AppContext,
    job_manager: JobManager,
    job_id: str | None,
    run_id: str | None,
) -> tuple[JobState | None, dict[str, Any] | None]:
    if job_id:
        job = job_manager.get_job(job_id)
        if job is not None:
            return job, job.record
    if run_id:
        return None, find_record_by_run_id(context, run_id)
    history = context.load_history()
    return None, history[0] if history else None


def collect_current_log_entries(
    context: pipeline_app.AppContext,
    job: JobState | None,
    record: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    entries = collect_log_entries(context, record if job is None else None)

    run_entry: dict[str, Any] | None = None
    if job is not None:
        if job.record and job.record.get("debug_log_file"):
            debug_path = Path(job.record["debug_log_file"])
            run_entry = {
                "key": "run",
                "label": "当前任务日志",
                "path": str(debug_path),
                "content": read_text_file(debug_path),
            }
        else:
            live_lines = list(job.logs)
            if job.error and not any(job.error in line for line in live_lines):
                live_lines.append(f"[error] {job.error}")
            run_entry = {
                "key": "run",
                "label": "当前任务日志",
                "path": "当前任务实时日志，任务完成后会写入运行目录。",
                "content": "\n".join(live_lines).strip(),
            }

    if run_entry is not None:
        entries.insert(0, run_entry)
    return entries


async def store_upload(
    upload: UploadFile | None,
    temp_dir: Path,
    base_name: str,
) -> str:
    if upload is None or not upload.filename:
        return ""
    suffix = Path(upload.filename).suffix.lower() or ".png"
    target_path = temp_dir / f"{base_name}{suffix}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(await upload.read())
    return str(target_path)


async def store_uploads(
    uploads: list[UploadFile] | None,
    temp_dir: Path,
    base_name: str,
) -> list[str]:
    saved_paths: list[str] = []
    for index, upload in enumerate(uploads or [], start=1):
        if upload is None or not upload.filename:
            continue
        suffix = Path(upload.filename).suffix.lower() or ".png"
        target_path = temp_dir / f"{base_name}-{index:02d}{suffix}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(await upload.read())
        saved_paths.append(str(target_path))
    return saved_paths


def create_api_server(
    *,
    project_root: Path,
    asset_root: Path,
) -> FastAPI:
    paths = ProjectPaths(
        project_root=project_root,
        asset_root=asset_root,
        web_dir=asset_root / "web",
        temp_upload_dir=project_root / "_runtime_uploads",
    )
    context = create_context(project_root, asset_root)
    context.ensure_layout()
    settings = validate_settings(context.load_settings())
    pipeline_app.configure_shared_render_gate(settings.default_concurrency)
    job_manager = JobManager(context)

    app = FastAPI(title=APP_TITLE)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=LOCAL_CORS_ORIGIN_REGEX,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next: Any) -> Any:
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logging.exception(
                "api request failed method=%s path=%s elapsedMs=%s",
                request.method,
                request.url.path,
                elapsed_ms,
            )
            raise
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        if response.status_code >= 400 or request.url.path in {"/api/health", "/api/bootstrap"}:
            logging.info(
                "api request method=%s path=%s status=%s elapsedMs=%s",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )
        return response

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/client-log")
    async def client_log(request: Request) -> dict[str, str]:
        try:
            payload = await request.json()
        except Exception as exc:
            logging.warning("client startup log parse failed: %s", exc)
            return {"status": "ignored"}
        logging.info("client startup log %s", json.dumps(payload, ensure_ascii=False))
        return {"status": "ok"}

    @app.get("/api/bootstrap")
    def bootstrap() -> dict[str, Any]:
        current_settings = validate_settings(context.load_settings())
        pipeline_app.configure_shared_render_gate(current_settings.default_concurrency)
        history = [serialize_record(item, context) for item in context.load_history()]
        jobs = [serialize_job(item, context) for item in job_manager.list_jobs()[:10]]
        return {
            "app_title": APP_TITLE,
            "pages": build_pages(),
            "settings": settings_payload(current_settings),
            "shared_pool": pipeline_app.shared_render_pool_status(),
            "history": history,
            "jobs": jobs,
            "edit_conversations": context.load_edit_conversations(),
        }

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return settings_payload(validate_settings(context.load_settings()))

    @app.get("/api/shared-pool")
    def get_shared_pool() -> dict[str, int]:
        return pipeline_app.shared_render_pool_status()

    @app.put("/api/settings")
    def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            current_settings = context.load_settings()
            merged_payload = merge_preserved_secret_settings(payload, current_settings)
            next_settings = validate_settings(pipeline_app.Settings.from_dict(merged_payload))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        context.save_settings(next_settings)
        pipeline_app.configure_shared_render_gate(next_settings.default_concurrency)
        return settings_payload(next_settings)

    @app.get("/api/history")
    def get_history() -> list[dict[str, Any]]:
        return [serialize_record(item, context) for item in context.load_history()]

    @app.get("/api/edit-conversations")
    def get_edit_conversations() -> dict[str, Any]:
        return {"conversations": context.load_edit_conversations()}

    @app.post("/api/edit-conversations")
    @app.put("/api/edit-conversations")
    def update_edit_conversations(payload: Any) -> dict[str, Any]:
        conversations = (
            payload.get("conversations")
            if isinstance(payload, dict)
            else payload
        )
        if not isinstance(conversations, list):
            raise HTTPException(status_code=400, detail="会话数据格式不正确。")
        context.save_edit_conversations(
            [item for item in conversations if isinstance(item, dict)]
        )
        return {
            "status": "ok",
            "count": len(conversations),
        }

    @app.delete("/api/edit-conversations/{conversation_id}")
    def remove_edit_conversation(conversation_id: str) -> dict[str, Any]:
        deleted = delete_edit_conversation(context, conversation_id)
        if deleted is None:
            raise HTTPException(status_code=404, detail="会话不存在。")
        for run_id in deleted["deleted_run_ids"]:
            job_manager.remove_run(run_id)
        return {"status": "deleted", **deleted}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        record = find_record_by_run_id(context, run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        return serialize_record(record, context)

    @app.delete("/api/runs/{run_id}")
    def delete_run(run_id: str) -> dict[str, Any]:
        record = delete_record_by_run_id(context, run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        job_manager.remove_run(run_id)
        return {"status": "deleted", "run_id": run_id}

    @app.post("/api/runs/{run_id}/open")
    def open_run(run_id: str) -> dict[str, str]:
        record = find_record_by_run_id(context, run_id) or find_active_summary_by_run_id(
            job_manager,
            run_id,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        try:
            pipeline_app.open_path(resolve_run_open_path(record))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"status": "opened"}

    @app.get("/api/runs/{run_id}/download")
    def download_run(run_id: str) -> FileResponse:
        record = find_record_by_run_id(context, run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        run_dir = Path(record["run_dir"])
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail="任务目录不存在。")
        zip_path = pipeline_app.export_run_zip(run_dir)
        return FileResponse(
            path=zip_path,
            filename=zip_path.name,
            media_type="application/zip",
        )

    @app.get("/api/thumbnails/{relative_path:path}")
    def get_thumbnail(relative_path: str) -> FileResponse:
        try:
            image_path = (context.data_dir / relative_path).resolve()
            image_path.relative_to(context.data_dir.resolve())
        except Exception as exc:
            raise HTTPException(status_code=404, detail="图片不存在。") from exc
        if not image_path.exists() or not image_path.is_file():
            raise HTTPException(status_code=404, detail="图片不存在。")
        thumbnail_path = pipeline_app.create_image_thumbnail(image_path)
        if not thumbnail_path:
            raise HTTPException(status_code=404, detail="缩略图生成失败。")
        return FileResponse(
            path=thumbnail_path,
            media_type="image/webp",
        )

    @app.get("/api/jobs")
    def get_jobs() -> list[dict[str, Any]]:
        return [serialize_job(item, context) for item in job_manager.list_jobs()]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = job_manager.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        return serialize_job(job, context)

    @app.get("/api/logs")
    def get_logs(job_id: str | None = None, run_id: str | None = None) -> dict[str, Any]:
        job, record = resolve_log_source(
            context=context,
            job_manager=job_manager,
            job_id=job_id,
            run_id=run_id,
        )
        entries = collect_current_log_entries(context, job, record)
        selected_key = "run" if entries and entries[0]["key"] == "run" else "app"
        return {
            "entries": entries,
            "selected_key": selected_key,
        }

    @app.post("/api/logs/open")
    def open_logs_dir() -> dict[str, str]:
        try:
            pipeline_app.open_path(context.logs_dir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"status": "opened"}

    @app.get("/api/clipboard/images")
    def get_clipboard_images() -> dict[str, Any]:
        try:
            items = collect_clipboard_images()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"items": items, "count": len(items)}

    @app.post("/api/data/open")
    def open_data_dir() -> dict[str, str]:
        try:
            pipeline_app.open_path(context.data_dir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"status": "opened"}

    def resolve_task_output_request_config(
        *,
        current_settings: pipeline_app.Settings,
        image_model: str | None = None,
        output_resolution: str,
        output_aspect_ratio: str,
        legacy_output: str,
    ) -> dict[str, str]:
        if output_resolution.strip() or output_aspect_ratio.strip():
            selected_resolution = (
                output_resolution.strip() or current_settings.default_output_resolution
            )
            selected_aspect_ratio = (
                output_aspect_ratio.strip()
                or current_settings.default_output_aspect_ratio
            )
        elif legacy_output.strip():
            selected_resolution, selected_aspect_ratio = (
                pipeline_app.parse_output_selection(legacy_output=legacy_output)
            )
        else:
            selected_resolution = current_settings.default_output_resolution
            selected_aspect_ratio = current_settings.default_output_aspect_ratio
        request_config = pipeline_app.resolve_image_request_config(
            output_resolution=selected_resolution,
            output_aspect_ratio=selected_aspect_ratio,
            settings=current_settings,
        )
        pipeline_app.resolve_effective_image_model(
            settings=current_settings,
            image_model=image_model or current_settings.image_model,
            output_resolution=request_config["output_resolution"],
            output_aspect_ratio=request_config["output_aspect_ratio"],
        )
        return request_config

    async def create_style_replicate_job_impl(
        prompt_count: str,
        output_resolution: str,
        output_aspect_ratio: str,
        aspect_ratio: str,
        user_prompt: str,
        style_url: str,
        product_url: str,
        style_files: list[UploadFile] | None,
        product_files: list[UploadFile] | None,
    ) -> JSONResponse:
        current_settings = validate_settings(context.load_settings())
        pipeline_app.configure_shared_render_gate(current_settings.default_concurrency)
        temp_dir = paths.temp_upload_dir / uuid.uuid4().hex
        try:
            resolved_user_prompt = (
                user_prompt.strip()
                or current_settings.default_user_prompt
                or pipeline_app.DEFAULT_USER_PROMPT
            )
            style_file_paths = await store_uploads(style_files, temp_dir, "style")
            product_file_paths = await store_uploads(product_files, temp_dir, "product")
            style_urls = pipeline_app.parse_reference_urls(style_url)
            product_urls = pipeline_app.parse_reference_urls(product_url)
            style_count = len(style_file_paths) + len(style_urls)
            product_count = len(product_file_paths) + len(product_urls)
            if style_count <= 0:
                raise HTTPException(status_code=400, detail="请上传或填写 1 至 5 张风格图。")
            if product_count <= 0:
                raise HTTPException(status_code=400, detail="请上传或填写 1 至 5 张产品图。")
            if style_count > pipeline_app.MAX_STYLE_REFERENCE_IMAGES:
                raise HTTPException(
                    status_code=400,
                    detail=f"风格图最多支持 {pipeline_app.MAX_STYLE_REFERENCE_IMAGES} 张。",
                )
            if product_count > pipeline_app.MAX_PRODUCT_REFERENCE_IMAGES:
                raise HTTPException(
                    status_code=400,
                    detail=f"产品图最多支持 {pipeline_app.MAX_PRODUCT_REFERENCE_IMAGES} 张。",
                )
            request_config = resolve_task_output_request_config(
                current_settings=current_settings,
                output_resolution=output_resolution,
                output_aspect_ratio=output_aspect_ratio,
                legacy_output=aspect_ratio,
            )
            options = pipeline_app.RunOptions(
                project_name=pipeline_app.generate_project_name(),
                prompt_count=pipeline_app.positive_int(prompt_count, "提示词数"),
                output_resolution=request_config["output_resolution"],
                output_aspect_ratio=request_config["output_aspect_ratio"],
                user_prompt=resolved_user_prompt,
                images_per_prompt=current_settings.default_images_per_prompt,
                concurrency=current_settings.default_concurrency,
                style_source=pipeline_app.SourceSpec(
                    file_paths=style_file_paths,
                    urls=style_urls,
                ),
                product_source=pipeline_app.SourceSpec(
                    file_paths=product_file_paths,
                    urls=product_urls,
                ),
            )

            job = job_manager.create_style_replicate_job(
                settings=current_settings,
                options=options,
                cleanup_dir=temp_dir,
                metadata={
                    "prompt_count": options.prompt_count,
                    "aspect_ratio": options.output_aspect_ratio,
                    "output_resolution": options.output_resolution,
                    "output_aspect_ratio": options.output_aspect_ratio,
                    "resolved_size": request_config["size"],
                    "output_label": request_config["label"],
                    "shared_pool_size": current_settings.default_concurrency,
                    "images_per_prompt": current_settings.default_images_per_prompt,
                    "style_reference_count": style_count,
                    "product_reference_count": product_count,
                },
            )
            return JSONResponse(
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "shared_pool_size": current_settings.default_concurrency,
                }
            )
        except HTTPException:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/tasks/style-replicate")
    async def create_style_replicate_job(
        prompt_count: str = Form(...),
        output_resolution: str = Form(""),
        output_aspect_ratio: str = Form(""),
        aspect_ratio: str = Form(""),
        user_prompt: str = Form(""),
        style_url: str = Form(""),
        product_url: str = Form(""),
        style_file: list[UploadFile] | None = File(default=None),
        product_file: list[UploadFile] | None = File(default=None),
    ) -> JSONResponse:
        return await create_style_replicate_job_impl(
            prompt_count=prompt_count,
            output_resolution=output_resolution,
            output_aspect_ratio=output_aspect_ratio,
            aspect_ratio=aspect_ratio,
            user_prompt=user_prompt,
            style_url=style_url,
            product_url=product_url,
            style_files=style_file,
            product_files=product_file,
        )

    @app.post("/api/tasks/style-replicate-v2")
    async def create_style_replicate2_job(
        prompt_count: str = Form(...),
        output_resolution: str = Form(""),
        output_aspect_ratio: str = Form(""),
        aspect_ratio: str = Form(""),
        user_prompt: str = Form(""),
        reference_url: str = Form(""),
        reference_file: list[UploadFile] | None = File(default=None),
    ) -> JSONResponse:
        current_settings = validate_settings(context.load_settings())
        pipeline_app.configure_shared_render_gate(current_settings.default_concurrency)
        temp_dir = paths.temp_upload_dir / uuid.uuid4().hex
        try:
            resolved_user_prompt = (
                user_prompt.strip()
                or current_settings.style_replicate2_user_prompt
                or pipeline_app.STYLE_REPLICATE2_DEFAULT_USER_PROMPT
            )
            reference_file_paths = await store_uploads(
                reference_file,
                temp_dir,
                "reference",
            )
            reference_urls = pipeline_app.parse_reference_urls(reference_url)
            reference_count = len(reference_file_paths) + len(reference_urls)
            if reference_count <= 0:
                raise HTTPException(status_code=400, detail="请上传或填写 1 至 10 张参考图。")
            if reference_count > pipeline_app.MAX_STYLE_REPLICATE2_REFERENCE_IMAGES:
                raise HTTPException(
                    status_code=400,
                    detail=f"参考图最多支持 {pipeline_app.MAX_STYLE_REPLICATE2_REFERENCE_IMAGES} 张。",
                )
            request_config = resolve_task_output_request_config(
                current_settings=current_settings,
                output_resolution=output_resolution,
                output_aspect_ratio=output_aspect_ratio,
                legacy_output=aspect_ratio,
            )
            options = pipeline_app.StyleReplicate2Options(
                project_name=pipeline_app.generate_project_name(),
                prompt_count=pipeline_app.positive_int(prompt_count, "提示词数"),
                output_resolution=request_config["output_resolution"],
                output_aspect_ratio=request_config["output_aspect_ratio"],
                user_prompt=resolved_user_prompt,
                images_per_prompt=current_settings.default_images_per_prompt,
                concurrency=current_settings.default_concurrency,
                reference_source=pipeline_app.SourceSpec(
                    file_paths=reference_file_paths,
                    urls=reference_urls,
                ),
            )
            job = job_manager.create_style_replicate2_job(
                settings=current_settings,
                options=options,
                cleanup_dir=temp_dir,
                metadata={
                    "project_name": options.project_name,
                    "prompt_count": options.prompt_count,
                    "aspect_ratio": options.output_aspect_ratio,
                    "output_resolution": options.output_resolution,
                    "output_aspect_ratio": options.output_aspect_ratio,
                    "resolved_size": request_config["size"],
                    "output_label": request_config["label"],
                    "shared_pool_size": current_settings.default_concurrency,
                    "images_per_prompt": current_settings.default_images_per_prompt,
                    "reference_count": reference_count,
                    "style_reference_count": reference_count,
                    "product_reference_count": 0,
                },
            )
            return JSONResponse(
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "shared_pool_size": current_settings.default_concurrency,
                }
            )
        except HTTPException:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/tasks/image-generate")
    async def create_legacy_image_job(
        prompt_count: str = Form(...),
        output_resolution: str = Form(""),
        output_aspect_ratio: str = Form(""),
        aspect_ratio: str = Form(""),
        user_prompt: str = Form(""),
        style_url: str = Form(""),
        product_url: str = Form(""),
        style_file: list[UploadFile] | None = File(default=None),
        product_file: list[UploadFile] | None = File(default=None),
    ) -> JSONResponse:
        return await create_style_replicate_job_impl(
            prompt_count=prompt_count,
            output_resolution=output_resolution,
            output_aspect_ratio=output_aspect_ratio,
            aspect_ratio=aspect_ratio,
            user_prompt=user_prompt,
            style_url=style_url,
            product_url=product_url,
            style_files=style_file,
            product_files=product_file,
        )

    @app.post("/api/tasks/image-edit")
    async def create_image_edit_job(
        prompt: str = Form(...),
        image_model: str = Form(""),
        output_resolution: str = Form(""),
        output_aspect_ratio: str = Form(""),
        aspect_ratio: str = Form(""),
        images_per_prompt: str = Form(""),
        conversation_id: str = Form(""),
        conversation_title: str = Form(""),
        input_files: list[UploadFile] | None = File(default=None),
    ) -> JSONResponse:
        current_settings = validate_settings(context.load_settings())
        pipeline_app.configure_shared_render_gate(current_settings.default_concurrency)
        temp_dir = paths.temp_upload_dir / uuid.uuid4().hex
        try:
            resolved_prompt = prompt.strip()
            if not resolved_prompt:
                raise HTTPException(status_code=400, detail="请填写图片生成提示词。")
            input_file_paths = await store_uploads(input_files, temp_dir, "edit")
            if len(input_file_paths) > pipeline_app.MAX_IMAGE_EDIT_INPUT_IMAGES:
                raise HTTPException(
                    status_code=400,
                    detail=f"图片生成最多支持 {pipeline_app.MAX_IMAGE_EDIT_INPUT_IMAGES} 张输入图。",
                )
            resolved_images_per_prompt = pipeline_app.positive_int(
                images_per_prompt.strip() or current_settings.default_images_per_prompt,
                "生成次数",
            )
            selected_image_model = pipeline_app.normalize_image_model(
                image_model.strip() or current_settings.image_model
            )
            request_config = resolve_task_output_request_config(
                current_settings=current_settings,
                image_model=selected_image_model,
                output_resolution=output_resolution,
                output_aspect_ratio=output_aspect_ratio,
                legacy_output=aspect_ratio,
            )
            options = pipeline_app.ImageEditOptions(
                project_name=pipeline_app.generate_project_name(),
                prompt=resolved_prompt,
                image_model=selected_image_model,
                output_resolution=request_config["output_resolution"],
                output_aspect_ratio=request_config["output_aspect_ratio"],
                images_per_prompt=resolved_images_per_prompt,
                input_images=input_file_paths,
                conversation_id=conversation_id.strip(),
                conversation_title=conversation_title.strip(),
            )

            job = job_manager.create_image_edit_job(
                settings=current_settings,
                options=options,
                cleanup_dir=temp_dir,
                metadata={
                    "prompt_count": 1,
                    "aspect_ratio": options.output_aspect_ratio,
                    "output_resolution": options.output_resolution,
                    "output_aspect_ratio": options.output_aspect_ratio,
                    "resolved_size": request_config["size"],
                    "output_label": request_config["label"],
                    "shared_pool_size": current_settings.default_concurrency,
                    "image_model": options.image_model,
                    "images_per_prompt": options.images_per_prompt,
                    "input_image_count": len(input_file_paths),
                },
            )
            return JSONResponse(
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "shared_pool_size": current_settings.default_concurrency,
                }
            )
        except HTTPException:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/tasks/image-agent")
    async def create_image_agent_job(
        prompt: str = Form(...),
        image_model: str = Form(""),
        conversation_id: str = Form(""),
        conversation_title: str = Form(""),
        conversation_context: str = Form(""),
        input_files: list[UploadFile] | None = File(default=None),
    ) -> JSONResponse:
        current_settings = validate_settings(context.load_settings())
        pipeline_app.configure_shared_render_gate(current_settings.default_concurrency)
        temp_dir = paths.temp_upload_dir / uuid.uuid4().hex
        try:
            resolved_prompt = prompt.strip()
            if not resolved_prompt:
                raise HTTPException(status_code=400, detail="请填写 Agent 图片生成需求。")
            input_file_paths = await store_uploads(input_files, temp_dir, "agent")
            if len(input_file_paths) > pipeline_app.MAX_IMAGE_EDIT_INPUT_IMAGES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Agent 模式最多支持 {pipeline_app.MAX_IMAGE_EDIT_INPUT_IMAGES} 张输入图。",
                )
            selected_image_model = pipeline_app.normalize_image_model(
                image_model.strip() or current_settings.image_model
            )
            options = pipeline_app.ImageAgentOptions(
                project_name=pipeline_app.generate_project_name(),
                prompt=resolved_prompt,
                image_model=selected_image_model,
                output_resolution="agent",
                output_aspect_ratio="agent",
                input_images=input_file_paths,
                conversation_id=conversation_id.strip(),
                conversation_title=conversation_title.strip(),
                conversation_context=conversation_context.strip(),
            )
            job = job_manager.create_image_agent_job(
                settings=current_settings,
                options=options,
                cleanup_dir=temp_dir,
                metadata={
                    "prompt_count": 0,
                    "aspect_ratio": "agent",
                    "output_resolution": "agent",
                    "output_aspect_ratio": "agent",
                    "resolved_size": "agent",
                    "output_label": "Agent 自动",
                    "shared_pool_size": current_settings.default_concurrency,
                    "image_model": options.image_model,
                    "image_agent_model": current_settings.image_agent_model,
                    "input_image_count": len(input_file_paths),
                },
            )
            return JSONResponse(
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "shared_pool_size": current_settings.default_concurrency,
                }
            )
        except HTTPException:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/tasks/color-match")
    async def create_color_match_job(
        output_resolution: str = Form(""),
        output_aspect_ratio: str = Form(""),
        aspect_ratio: str = Form(""),
        tone_file: UploadFile | None = File(default=None),
        scene_file: UploadFile | None = File(default=None),
    ) -> JSONResponse:
        current_settings = validate_settings(context.load_settings())
        pipeline_app.configure_shared_render_gate(current_settings.default_concurrency)
        temp_dir = paths.temp_upload_dir / uuid.uuid4().hex
        try:
            tone_file_path = await store_upload(tone_file, temp_dir, "tone")
            scene_file_path = await store_upload(scene_file, temp_dir, "scene")
            if not tone_file_path:
                raise HTTPException(status_code=400, detail="请上传色调参考图。")
            if not scene_file_path:
                raise HTTPException(status_code=400, detail="请上传静物场景图。")
            request_config = resolve_task_output_request_config(
                current_settings=current_settings,
                output_resolution=output_resolution,
                output_aspect_ratio=output_aspect_ratio,
                legacy_output=aspect_ratio,
            )
            options = pipeline_app.ColorMatchOptions(
                project_name=pipeline_app.generate_project_name(),
                output_resolution=request_config["output_resolution"],
                output_aspect_ratio=request_config["output_aspect_ratio"],
                tone_image=tone_file_path,
                scene_image=scene_file_path,
            )
            job = job_manager.create_color_match_job(
                settings=current_settings,
                options=options,
                cleanup_dir=temp_dir,
                metadata={
                    "prompt_count": 2,
                    "aspect_ratio": options.output_aspect_ratio,
                    "output_resolution": options.output_resolution,
                    "output_aspect_ratio": options.output_aspect_ratio,
                    "resolved_size": request_config["size"],
                    "output_label": request_config["label"],
                    "shared_pool_size": current_settings.default_concurrency,
                    "images_per_prompt": 1,
                    "input_image_count": 2,
                    "color_match_model": current_settings.color_match_model,
                },
            )
            return JSONResponse(
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "shared_pool_size": current_settings.default_concurrency,
                }
            )
        except HTTPException:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.exception_handler(HTTPException)
    async def http_error_handler(_request: Any, exc: HTTPException) -> JSONResponse:
        logging.warning(
            "api HTTPException status=%s detail=%s",
            exc.status_code,
            exc.detail,
        )
        payload = error_payload(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=payload,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logging.exception(
            "api unhandled exception method=%s path=%s",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content=error_payload("服务器内部错误，请查看 backend-server.log。"),
        )

    app.mount("/data", StaticFiles(directory=str(context.data_dir)), name="data")
    if paths.web_dir.exists():
        app.mount("/", StaticFiles(directory=str(paths.web_dir), html=True), name="web")
    return app
