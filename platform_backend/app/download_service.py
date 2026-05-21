from __future__ import annotations

import hashlib
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import CONFIG
from .legacy_contract import (
    IMAGE_SUFFIXES,
    image_thumbnail_url,
    path_to_pipeline_file_url,
    read_json_file,
    thumbnail_path_for_image,
)
from .storage_service import job_storage_dir


PACKAGE_SUFFIXES = IMAGE_SUFFIXES | {".json", ".txt", ".log", ".md"}
JOB_FILE_FOLDERS = {"inputs", "outputs", "thumbnails", "json"}
DOWNLOAD_TTL_HOURS = 24


@dataclass(frozen=True)
class DownloadFile:
    id: str
    kind: str
    path: Path
    relative_path: str
    name: str
    size_bytes: int
    url: str | None = None
    thumbnail_url: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "url": self.url,
            "thumbnail_url": self.thumbnail_url,
        }


def _job_base(job: dict[str, Any]) -> Path:
    return job_storage_dir(job["user_id"], job["id"]).resolve()


def _safe_file_path(value: Any, base_dir: Path) -> Path | None:
    if not value:
        return None
    try:
        target = Path(str(value)).expanduser().resolve()
        target.relative_to(base_dir)
    except Exception:
        return None
    if not target.exists() or not target.is_file():
        return None
    return target


def _safe_name(value: str, fallback: str) -> str:
    name = Path(value or fallback).name or fallback
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .") or fallback


def _file_id(relative_path: str, kind: str) -> str:
    digest = hashlib.sha1(f"{kind}:{relative_path}".encode("utf-8")).hexdigest()[:16]
    return f"{kind}-{digest}"


def _job_file_url(path: Path, job: dict[str, Any], base_dir: Path) -> str | None:
    pipeline_url = path_to_pipeline_file_url(path, job)
    if pipeline_url:
        return pipeline_url
    try:
        relative = path.relative_to(base_dir)
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) == 2 and parts[0] in JOB_FILE_FOLDERS:
        return f"/api/v1/files/{job['user_id']}/jobs/{job['id']}/{parts[0]}/{parts[1]}"
    return None


def cleanup_old_downloads(max_age_hours: int = DOWNLOAD_TTL_HOURS) -> int:
    target_dir = CONFIG.base_dir / "downloads"
    if not target_dir.exists():
        return 0
    cutoff = time.time() - max(1, int(max_age_hours)) * 60 * 60
    deleted = 0
    for path in target_dir.glob("*.zip"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                deleted += 1
        except OSError:
            continue
    return deleted


def _add_file(
    files: list[DownloadFile],
    seen: set[str],
    path_value: Any,
    *,
    job: dict[str, Any],
    base_dir: Path,
    kind: str,
    thumbnail_path: Any = None,
) -> DownloadFile | None:
    path = _safe_file_path(path_value, base_dir)
    if not path:
        return None
    suffix = path.suffix.lower()
    if kind in {"image", "thumbnail"} and suffix not in IMAGE_SUFFIXES:
        return None
    if kind not in {"image", "thumbnail"} and suffix not in PACKAGE_SUFFIXES:
        return None
    relative_path = path.relative_to(base_dir).as_posix()
    dedupe_key = f"{kind}:{relative_path}"
    if dedupe_key in seen:
        return None
    seen.add(dedupe_key)
    explicit_thumb = _safe_file_path(thumbnail_path, base_dir) if thumbnail_path else None
    thumbnail_url = None
    if kind == "image":
        thumbnail_url = image_thumbnail_url(
            path,
            job,
            explicit_thumbnail_path=explicit_thumb,
        )
    item = DownloadFile(
        id=_file_id(relative_path, kind),
        kind=kind,
        path=path,
        relative_path=relative_path,
        name=_safe_name(path.name, f"{kind}{suffix or '.bin'}"),
        size_bytes=path.stat().st_size,
        url=_job_file_url(path, job, base_dir),
        thumbnail_url=thumbnail_url,
    )
    files.append(item)
    return item


def _iter_summary_images(summary: dict[str, Any]) -> list[tuple[Any, Any]]:
    pairs: list[tuple[Any, Any]] = []
    renders = summary.get("renders", [])
    if not isinstance(renders, list):
        renders = []
    for render in renders:
        if not isinstance(render, dict):
            continue
        thumbs: dict[str, Any] = {}
        details = render.get("image_details")
        if isinstance(details, list):
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                image_path = detail.get("path")
                thumb_path = detail.get("thumbnail_path")
                if image_path and thumb_path:
                    thumbs[str(image_path)] = thumb_path
        image_paths = render.get("images", [])
        if not isinstance(image_paths, list):
            image_paths = []
        for image_path in image_paths:
            pairs.append((image_path, thumbs.get(str(image_path))))

    outputs = summary.get("color_match_outputs")
    if isinstance(outputs, dict):
        for value in outputs.values():
            if not isinstance(value, dict):
                continue
            image_paths = value.get("images", [])
            if not isinstance(image_paths, list):
                image_paths = []
            for image_path in image_paths:
                pairs.append((image_path, None))
    return pairs


def collect_job_download_files(job: dict[str, Any]) -> dict[str, Any]:
    base_dir = _job_base(job)
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    record = result.get("record") if isinstance(result.get("record"), dict) else {}
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
    raw_summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    if not raw_summary and record:
        raw_summary = read_json_file(record.get("summary_file"))

    image_files: list[DownloadFile] = []
    package_files: list[DownloadFile] = []
    seen_images: set[str] = set()
    seen_package: set[str] = set()

    def add_image(path_value: Any, thumbnail_path: Any = None) -> None:
        item = _add_file(
            image_files,
            seen_images,
            path_value,
            job=job,
            base_dir=base_dir,
            kind="image",
            thumbnail_path=thumbnail_path,
        )
        if item:
            _add_file(
                package_files,
                seen_package,
                item.path,
                job=job,
                base_dir=base_dir,
                kind="image",
                thumbnail_path=thumbnail_path,
            )
            thumb = _safe_file_path(thumbnail_path, base_dir) if thumbnail_path else None
            if not thumb:
                thumb = thumbnail_path_for_image(item.path)
            if thumb:
                _add_file(
                    package_files,
                    seen_package,
                    thumb,
                    job=job,
                    base_dir=base_dir,
                    kind="thumbnail",
                )

    latest_images = record.get("latest_images", [])
    if not isinstance(latest_images, list):
        latest_images = []
    for image_path in latest_images:
        add_image(image_path)
    for image_path, thumbnail_path in _iter_summary_images(raw_summary):
        add_image(image_path, thumbnail_path)

    if not image_files:
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            kind = str(artifact.get("kind") or "")
            mime_type = str(artifact.get("mime_type") or "")
            path = artifact.get("path")
            suffix = Path(str(path or "")).suffix.lower()
            if kind.startswith("image") or mime_type.startswith("image/") or suffix in IMAGE_SUFFIXES:
                add_image(path)

    diagnostic_paths = [
        record.get("summary_file"),
        record.get("debug_log_file"),
        raw_summary.get("prompts_file") if isinstance(raw_summary, dict) else None,
        raw_summary.get("prompt_request_file") if isinstance(raw_summary, dict) else None,
        raw_summary.get("prompt_response_file") if isinstance(raw_summary, dict) else None,
        raw_summary.get("render_manifest_file") if isinstance(raw_summary, dict) else None,
        raw_summary.get("debug_log_file") if isinstance(raw_summary, dict) else None,
        raw_summary.get("color_analysis_file") if isinstance(raw_summary, dict) else None,
    ]
    if isinstance(raw_summary, dict):
        renders = raw_summary.get("renders", [])
        if not isinstance(renders, list):
            renders = []
        for render in renders:
            if isinstance(render, dict):
                diagnostic_paths.append(render.get("response_file"))

    for path_value in diagnostic_paths:
        _add_file(
            package_files,
            seen_package,
            path_value,
            job=job,
            base_dir=base_dir,
            kind="document",
        )

    for folder in ("json", "pipeline/logs"):
        folder_path = base_dir / folder
        if folder_path.exists():
            for path in folder_path.rglob("*"):
                if path.is_file():
                    _add_file(
                        package_files,
                        seen_package,
                        path,
                        job=job,
                        base_dir=base_dir,
                        kind="document",
                    )

    return {
        "images": image_files,
        "package_files": package_files,
    }


def _zip_arcname(file: DownloadFile, index: int, *, scope: str) -> str:
    suffix = file.path.suffix.lower() or ".bin"
    if scope == "images":
        return f"images/{index:02d}-{_safe_name(file.name, f'image-{index:02d}{suffix}')}"
    if file.kind == "image":
        return f"images/{index:02d}-{_safe_name(file.name, f'image-{index:02d}{suffix}')}"
    if file.kind == "thumbnail":
        return f"thumbnails/{index:02d}-{_safe_name(file.name, f'thumb-{index:02d}{suffix}')}"
    return f"task-files/{file.relative_path}"


def build_job_zip(
    job: dict[str, Any],
    *,
    scope: str = "images",
    selected_ids: set[str] | None = None,
) -> tuple[Path, str]:
    cleanup_old_downloads()
    scope = "task" if scope == "task" else "images"
    files_payload = collect_job_download_files(job)
    source_files: list[DownloadFile] = (
        files_payload["package_files"] if scope == "task" else files_payload["images"]
    )
    if selected_ids is not None:
        source_files = [item for item in source_files if item.id in selected_ids]
    if not source_files:
        raise ValueError("no_files")

    target_dir = CONFIG.base_dir / "downloads"
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(
        f"{job['id']}:{scope}:{','.join(item.id for item in source_files)}".encode("utf-8")
    ).hexdigest()[:12]
    target = target_dir / f"{job['id']}-{scope}-{digest}.zip"
    filename = f"design-output-{job['id']}-{scope}.zip"

    used_names: set[str] = set()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, file in enumerate(source_files, start=1):
            arcname = _zip_arcname(file, index, scope=scope)
            if arcname in used_names:
                stem = Path(arcname).stem
                suffix = Path(arcname).suffix
                parent = Path(arcname).parent.as_posix()
                arcname = f"{parent}/{stem}-{index:02d}{suffix}"
            used_names.add(arcname)
            archive.write(file.path, arcname)
    return target, filename
