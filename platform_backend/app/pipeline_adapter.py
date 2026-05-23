from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

import pipeline_core as pipeline_app

from .storage_service import job_storage_dir, register_artifact
from .task_service import add_job_event, allocate_user_image_sequence


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
DOCUMENT_SUFFIXES = {".json", ".txt", ".log", ".md"}
_LOG_EVENT_PREFIX_LENGTH = len("[YYYY-MM-DD HH:MM:SS] ")


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


def _sequence_prefix(block_index: int) -> str:
    if block_index <= 0:
        return ""
    letters = []
    value = block_index
    while value > 0:
        value -= 1
        letters.append(chr(ord("a") + (value % 26)))
        value //= 26
    return "".join(reversed(letters))


def image_sequence_label(value: int) -> str:
    safe_value = max(1, int(value))
    block_index = (safe_value - 1) // 1000
    number = ((safe_value - 1) % 1000) + 1
    if block_index == 0:
        return f"{number:02d}" if number < 100 else str(number)
    return f"{_sequence_prefix(block_index)}{number}"


def _copy_to_pipeline_location(source: Path, target: Path) -> None:
    if source.resolve() == target.resolve():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    source_thumb = pipeline_app.thumbnail_path_for_image(source)
    target_thumb = pipeline_app.thumbnail_path_for_image(target)
    if source_thumb.exists():
        target_thumb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_thumb, target_thumb)


def _refresh_record_image_paths(record: dict[str, Any], rename_map: dict[str, str]) -> None:
    if not rename_map:
        return

    resolved_rename_map = {
        str(Path(source).resolve()): target
        for source, target in rename_map.items()
    }

    def replace_value(value: Any) -> Any:
        if isinstance(value, str):
            if value in rename_map:
                return rename_map[value]
            try:
                resolved_value = str(Path(value).expanduser().resolve())
            except Exception:
                resolved_value = ""
            return resolved_rename_map.get(value) or resolved_rename_map.get(resolved_value) or value
        if isinstance(value, list):
            return [replace_value(item) for item in value]
        if isinstance(value, dict):
            return {key: replace_value(item) for key, item in value.items()}
        return value

    record["latest_images"] = replace_value(record.get("latest_images", []))

    summary_path = record.get("summary_file")
    if not summary_path:
        return
    path = Path(str(summary_path))
    if not path.exists() or not path.is_file():
        return
    summary = pipeline_app.read_json_file(path, {})
    if not isinstance(summary, dict) or not summary:
        return
    summary = replace_value(summary)
    pipeline_app.write_json(path, summary)


def _append_unique_path(paths: list[Path], value: Any, seen: set[Path]) -> None:
    if not value:
        return
    try:
        path = Path(str(value)).expanduser().resolve()
    except Exception:
        return
    if path in seen or not path.exists() or not path.is_file():
        return
    if path.suffix.lower() not in IMAGE_SUFFIXES or path.parent.name == "_thumbs":
        return
    seen.add(path)
    paths.append(path)


def _summary_image_sources(record: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()

    latest_images = record.get("latest_images")
    if isinstance(latest_images, list):
        for image_path in latest_images:
            _append_unique_path(paths, image_path, seen)

    summary_file = record.get("summary_file")
    summary = pipeline_app.read_json_file(Path(str(summary_file)), {}) if summary_file else {}
    renders = summary.get("renders", []) if isinstance(summary, dict) else []
    if isinstance(renders, list):
        for render in renders:
            if not isinstance(render, dict):
                continue
            render_images = render.get("images", [])
            if not isinstance(render_images, list):
                continue
            for image_path in render_images:
                _append_unique_path(paths, image_path, seen)

    outputs = summary.get("color_match_outputs") if isinstance(summary, dict) else None
    if isinstance(outputs, dict):
        for output in outputs.values():
            if not isinstance(output, dict):
                continue
            output_images = output.get("images", [])
            if not isinstance(output_images, list):
                continue
            for image_path in output_images:
                _append_unique_path(paths, image_path, seen)

    if paths:
        return paths

    run_dir_text = str(record.get("run_dir") or "")
    if not run_dir_text:
        return paths
    images_dir = Path(run_dir_text) / "images"
    if not images_dir.exists() or not images_dir.is_dir():
        return paths
    for path in sorted(images_dir.rglob("*")):
        _append_unique_path(paths, path, seen)
    return paths


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
    image_sources: list[Path] = []
    diagnostic_sources: list[Path] = []
    renamed_image_paths: dict[str, str] = {}

    def collect_file(source: Path, bucket: list[Path]) -> None:
        if not source.exists() or not source.is_file():
            return
        resolved = source.resolve()
        if resolved in copied_sources:
            return
        copied_sources.add(resolved)
        bucket.append(resolved)

    def collect_diagnostic(source: Path) -> None:
        if not source.exists() or not source.is_file():
            return
        resolved = source.resolve()
        if resolved in diagnostic_sources:
            return
        diagnostic_sources.append(resolved)

    def copy_file(source: Path, target_dir: Path, kind: str, target_name: str | None = None) -> None:
        target = target_dir / (target_name or source.name)
        if target.exists():
            target = target_dir / f"{target.stem}-{len(artifacts) + 1:03d}{target.suffix}"
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

    def copy_image_with_thumbnail(source: Path, sequence_value: int) -> None:
        label = image_sequence_label(sequence_value)
        target_name = f"{label}{source.suffix.lower() or source.suffix or '.png'}"
        pipeline_target = source.parent / target_name
        _copy_to_pipeline_location(source, pipeline_target)
        renamed_image_paths[str(source.resolve())] = str(pipeline_target)
        copy_file(pipeline_target, output_dir, "image", target_name=target_name)
        pipeline_thumbnail = pipeline_app.thumbnail_path_for_image(pipeline_target)
        if pipeline_thumbnail.exists() and pipeline_thumbnail.resolve() not in copied_sources:
            copied_sources.add(pipeline_thumbnail.resolve())
            copy_file(
                pipeline_thumbnail.resolve(),
                output_dir,
                "image-thumbnail",
                target_name=f"{label}.thumb{pipeline_thumbnail.suffix.lower() or '.webp'}",
            )

    run_dir_text = str(record.get("run_dir") or "")
    if run_dir_text:
        run_dir = Path(run_dir_text)
        for path in sorted(run_dir.rglob("*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in DOCUMENT_SUFFIXES:
                collect_diagnostic(path)

    for image_source in _summary_image_sources(record):
        collect_file(image_source, image_sources)

    for key in ("summary_file", "render_manifest_file", "debug_log_file"):
        value = record.get(key)
        if value:
            collect_diagnostic(Path(str(value)))

    if image_sources:
        start = allocate_user_image_sequence(
            user_id=job["user_id"],
            count=len(image_sources),
        )
        for offset, source in enumerate(image_sources):
            copy_image_with_thumbnail(source, start + offset)
        _refresh_record_image_paths(record, renamed_image_paths)

    for source in diagnostic_sources:
        copy_file(source, json_dir, "diagnostic")

    return artifacts


def _create_job_event_logger(job: dict[str, Any]):
    last_event_by_message: dict[str, float] = {}

    def log_event(line: str) -> None:
        message = str(line or "").strip()
        if not message:
            return
        if message.startswith("[") and "] " in message:
            message = message[_LOG_EVENT_PREFIX_LENGTH:] if len(message) > _LOG_EVENT_PREFIX_LENGTH else message
        now = time.monotonic()
        previous = last_event_by_message.get(message)
        if previous is not None and now - previous < 1:
            return
        last_event_by_message[message] = now
        level = "error" if any(token in message for token in ("失败", "错误", "异常", "Traceback")) else "info"
        try:
            add_job_event(
                job_id=job["id"],
                user_id=job["user_id"],
                message=message,
                level=level,
            )
        except Exception:
            pass

    return log_event


def _progress_callback(job: dict[str, Any]):
    def update_progress(summary: dict[str, Any]) -> None:
        if not isinstance(summary, dict):
            return
        completed = int(summary.get("completed_request_count") or 0)
        failed = int(summary.get("failed_request_count") or 0)
        total = int(
            summary.get("request_count")
            or summary.get("prompt_count")
            or completed
            or 0
        )
        rendered = int(summary.get("rendered_image_count") or 0)
        phase = str(summary.get("phase") or summary.get("status") or "running")
        parts = [f"进度：{completed + failed}/{total}" if total else "进度更新"]
        if rendered:
            parts.append(f"已保存图片 {rendered} 张")
        if phase and phase != "running":
            parts.append(f"阶段 {phase}")
        if failed:
            parts.append(f"失败请求 {failed} 个")
        add_job_event(
            job_id=job["id"],
            user_id=job["user_id"],
            message="，".join(parts),
            level="warning" if failed else "info",
        )

    return update_progress


def run_pipeline_job(job: dict[str, Any]) -> dict[str, Any]:
    task_type = job["task_type"]
    payload = _job_payload(job)
    settings = _job_settings(job)
    context = _pipeline_context(job)
    context.ensure_layout()
    context.save_settings(settings)
    logger = pipeline_app.AppLogger(
        context.app_log_path,
        ui_callback=_create_job_event_logger(job),
    )
    progress_callback = _progress_callback(job)
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
        record = pipeline_app.run_image_edit_pipeline(
            context,
            settings,
            options,
            logger,
            progress_callback=progress_callback,
        )
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
        record = pipeline_app.run_image_agent_pipeline(
            context,
            settings,
            options,
            logger,
            progress_callback=progress_callback,
        )
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
