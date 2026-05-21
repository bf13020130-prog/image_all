from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pipeline_core as pipeline_app

from .storage_service import job_storage_dir, register_artifact
from .task_service import add_job_event


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def _job_payload(job: dict[str, Any]) -> dict[str, Any]:
    return job.get("payload") if isinstance(job.get("payload"), dict) else {}


def _job_settings(job: dict[str, Any]) -> pipeline_app.Settings:
    settings = job.get("effective_settings")
    if isinstance(settings, dict):
        return pipeline_app.Settings.from_dict(settings)
    return pipeline_app.Settings.from_dict({})


def _bounded_concurrency(payload: dict[str, Any], settings: pipeline_app.Settings) -> int:
    try:
        requested = int(payload.get("concurrency") or settings.default_concurrency)
    except (TypeError, ValueError):
        requested = settings.default_concurrency
    limit = max(1, int(settings.default_concurrency or 1))
    return max(1, min(requested, limit))


def _uploads(payload: dict[str, Any]) -> list[str]:
    items = payload.get("uploads")
    if not isinstance(items, list):
        return []
    paths: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("path"):
            paths.append(str(item["path"]))
    return paths


def _source_from_paths(paths: list[str]) -> pipeline_app.SourceSpec:
    return pipeline_app.SourceSpec(file_paths=paths)


def _source_from_payload(payload: dict[str, Any], key: str) -> pipeline_app.SourceSpec:
    file_paths = [
        str(item)
        for item in payload.get(f"{key}_file_paths", [])
        if str(item).strip()
    ] if isinstance(payload.get(f"{key}_file_paths"), list) else []
    urls = pipeline_app.parse_reference_urls(payload.get(f"{key}_url", ""))
    return pipeline_app.SourceSpec(file_paths=file_paths, urls=urls)


def _pipeline_context(job: dict[str, Any]) -> pipeline_app.AppContext:
    root = job_storage_dir(job["user_id"], job["id"]) / "pipeline"
    return pipeline_app.AppContext(
        root_dir=root,
        data_dir=root / "data",
        logs_dir=root / "logs",
        config_path=root / "config.json",
        config_example_path=Path("config.example.json").resolve(),
        history_path=root / "data" / "history.json",
        edit_conversations_path=root / "data" / "edit_conversations.json",
        app_log_path=root / "logs" / "app.log",
    )


def _copy_registered_artifacts(
    *,
    job: dict[str, Any],
    record: dict[str, Any],
) -> list[dict[str, Any]]:
    job_dir = job_storage_dir(job["user_id"], job["id"])
    output_dir = job_dir / "outputs"
    json_dir = job_dir / "json"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)

    artifacts: list[dict[str, Any]] = []
    copied_sources: set[Path] = set()

    def copy_file(source: Path, target_dir: Path, kind: str) -> None:
        if not source.exists() or not source.is_file():
            return
        resolved = source.resolve()
        if resolved in copied_sources:
            return
        copied_sources.add(resolved)
        target = target_dir / source.name
        if target.exists():
            target = target_dir / f"{source.stem}-{len(copied_sources):03d}{source.suffix}"
        shutil.copy2(source, target)
        artifacts.append(
            register_artifact(
                job_id=job["id"],
                user_id=job["user_id"],
                kind=kind,
                path=target,
                url=f"/api/v1/files/{job['user_id']}/jobs/{job['id']}/{target_dir.name}/{target.name}",
            )
        )

    run_dir_text = str(record.get("run_dir") or "")
    if run_dir_text:
        run_dir = Path(run_dir_text)
        for path in sorted(run_dir.rglob("*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in IMAGE_SUFFIXES:
                copy_file(path, output_dir, "image")
            elif suffix in {".json", ".txt", ".log", ".md"}:
                copy_file(path, json_dir, "diagnostic")

    for key in ("summary_file", "render_manifest_file", "debug_log_file"):
        value = record.get(key)
        if value:
            copy_file(Path(str(value)), json_dir, "diagnostic")

    return artifacts


def run_pipeline_job(job: dict[str, Any]) -> dict[str, Any]:
    task_type = job["task_type"]
    payload = _job_payload(job)
    settings = _job_settings(job)
    context = _pipeline_context(job)
    context.ensure_layout()
    context.save_settings(settings)
    logger = pipeline_app.AppLogger(context.app_log_path)
    uploads = _uploads(payload)
    output_resolution = str(
        payload.get("output_resolution")
        or settings.default_output_resolution
        or "auto"
    )
    output_aspect_ratio = str(
        payload.get("output_aspect_ratio")
        or settings.default_output_aspect_ratio
        or "auto"
    )
    image_model = str(payload.get("image_model") or settings.image_model)
    prompt = str(payload.get("prompt") or payload.get("user_prompt") or "").strip()

    add_job_event(
        job_id=job["id"],
        user_id=job["user_id"],
        message=f"开始调用现有 pipeline_core：{task_type}",
    )

    if task_type == "image-edit":
        options = pipeline_app.ImageEditOptions(
            project_name=payload.get("project_name") or job["id"],
            prompt=prompt,
            image_model=image_model,
            output_resolution=output_resolution,
            output_aspect_ratio=output_aspect_ratio,
            images_per_prompt=int(payload.get("images_per_prompt") or 1),
            input_images=uploads,
            conversation_id=str(payload.get("conversation_id") or ""),
            conversation_title=str(payload.get("conversation_title") or ""),
        )
        record = pipeline_app.run_image_edit_pipeline(context, settings, options, logger)
    elif task_type == "image-agent":
        options = pipeline_app.ImageAgentOptions(
            project_name=payload.get("project_name") or job["id"],
            prompt=prompt,
            image_model=image_model,
            output_resolution="agent",
            output_aspect_ratio="agent",
            input_images=uploads,
            conversation_id=str(payload.get("conversation_id") or ""),
            conversation_title=str(payload.get("conversation_title") or ""),
            conversation_context=str(payload.get("conversation_context") or ""),
        )
        record = pipeline_app.run_image_agent_pipeline(context, settings, options, logger)
    elif task_type == "color-match":
        if len(uploads) < 2:
            raise pipeline_app.AppError("一键追色需要至少 2 张图：色调参考图和静物场景图。")
        options = pipeline_app.ColorMatchOptions(
            project_name=payload.get("project_name") or job["id"],
            output_resolution=output_resolution,
            output_aspect_ratio=output_aspect_ratio,
            tone_image=uploads[0],
            scene_image=uploads[1],
        )
        record = pipeline_app.run_color_match_pipeline(context, settings, options, logger)
    elif task_type == "style-replicate-v2":
        reference = _source_from_payload(payload, "reference")
        if not reference.file_paths and not reference.urls:
            reference = _source_from_paths(uploads)
        options = pipeline_app.StyleReplicate2Options(
            project_name=payload.get("project_name") or job["id"],
            prompt_count=int(payload.get("prompt_count") or settings.default_prompt_count),
            output_resolution=output_resolution,
            output_aspect_ratio=output_aspect_ratio,
            user_prompt=prompt or settings.style_replicate2_user_prompt,
            images_per_prompt=int(payload.get("images_per_prompt") or settings.default_images_per_prompt),
            concurrency=_bounded_concurrency(payload, settings),
            reference_source=reference,
        )
        record = pipeline_app.run_style_replicate2_pipeline(context, settings, options, logger)
    elif task_type == "style-replicate":
        style_source = _source_from_payload(payload, "style")
        product_source = _source_from_payload(payload, "product")
        if (not style_source.file_paths and not style_source.urls) or (
            not product_source.file_paths and not product_source.urls
        ):
            if len(uploads) < 2:
                raise pipeline_app.AppError("复刻风格图片需要风格图和产品图。")
            split_at = max(1, len(uploads) // 2)
            style_source = _source_from_paths(uploads[:split_at])
            product_source = _source_from_paths(uploads[split_at:])
        options = pipeline_app.RunOptions(
            project_name=payload.get("project_name") or job["id"],
            prompt_count=int(payload.get("prompt_count") or settings.default_prompt_count),
            output_resolution=output_resolution,
            output_aspect_ratio=output_aspect_ratio,
            user_prompt=prompt or settings.default_user_prompt,
            images_per_prompt=int(payload.get("images_per_prompt") or settings.default_images_per_prompt),
            concurrency=_bounded_concurrency(payload, settings),
            style_source=style_source,
            product_source=product_source,
        )
        record = pipeline_app.run_pipeline(context, settings, options, logger)
    else:
        raise pipeline_app.AppError(f"不支持的任务类型：{task_type}")

    artifacts = _copy_registered_artifacts(job=job, record=record)
    summary = {}
    summary_file = record.get("summary_file") if isinstance(record, dict) else ""
    if summary_file:
        loaded_summary = pipeline_app.read_json_file(Path(str(summary_file)), {})
        if isinstance(loaded_summary, dict):
            summary = loaded_summary
    return {
        "record": record,
        "summary": summary,
        "artifacts": artifacts,
    }
