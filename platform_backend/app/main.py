from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import pipeline_core as pipeline_app

from .auth import require_active_user, require_admin
from .config import CONFIG
from .database import init_db
from .download_service import cleanup_old_downloads
from .task_service import cleanup_expired_job_history, cleanup_expired_logs
from .routers import admin, auth, legacy_web, me, tasks


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def media_type_for_path(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".webp":
        return "image/webp"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".json":
        return "application/json"
    if suffix in {".txt", ".log", ".md"}:
        return "text/plain; charset=utf-8"
    return mimetypes.guess_type(path.name)[0]


def create_app() -> FastAPI:
    app = FastAPI(title=CONFIG.app_name)
    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(tasks.router)
    app.include_router(admin.router)
    app.include_router(legacy_web.router)

    @app.on_event("startup")
    def startup() -> None:
        init_db()
        cleanup_old_downloads()
        cleanup_expired_job_history(retention_days=CONFIG.history_retention_days)
        cleanup_expired_logs(retention_days=CONFIG.log_retention_days)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/files/{owner_id}/jobs/{job_id}/{folder}/{filename}")
    def get_file(
        owner_id: str,
        job_id: str,
        folder: str,
        filename: str,
        user: dict = Depends(require_active_user),
    ) -> FileResponse:
        if user["id"] != owner_id:
            require_admin(user)
        if folder not in {"inputs", "outputs", "thumbnails", "json"}:
            raise HTTPException(status_code=404, detail="文件不存在。")
        base_dir = (CONFIG.storage_dir / "users" / owner_id / "jobs" / job_id / folder).resolve()
        target = (base_dir / filename).resolve()
        try:
            target.relative_to(base_dir)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="文件不存在。") from exc
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="文件不存在。")
        return FileResponse(target, media_type=media_type_for_path(target))

    def resolve_pipeline_file(
        *,
        owner_id: str,
        job_id: str,
        relative_path: str,
        user: dict,
    ) -> Path:
        if user["id"] != owner_id:
            require_admin(user)
        base_dir = (
            CONFIG.storage_dir / "users" / owner_id / "jobs" / job_id / "pipeline" / "data"
        ).resolve()
        target = (base_dir / relative_path).resolve()
        try:
            target.relative_to(base_dir)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="文件不存在。") from exc
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="文件不存在。")
        return target

    @app.get("/api/v1/pipeline-files/{owner_id}/jobs/{job_id}/{relative_path:path}")
    def get_pipeline_file(
        owner_id: str,
        job_id: str,
        relative_path: str,
        user: dict = Depends(require_active_user),
    ) -> FileResponse:
        target = resolve_pipeline_file(
            owner_id=owner_id,
            job_id=job_id,
            relative_path=relative_path,
            user=user,
        )
        return FileResponse(target, media_type=media_type_for_path(target))

    @app.get("/api/v1/pipeline-thumbnails/{owner_id}/jobs/{job_id}/{relative_path:path}")
    def get_pipeline_thumbnail(
        owner_id: str,
        job_id: str,
        relative_path: str,
        user: dict = Depends(require_active_user),
    ) -> FileResponse:
        image_path = resolve_pipeline_file(
            owner_id=owner_id,
            job_id=job_id,
            relative_path=relative_path,
            user=user,
        )
        if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
            raise HTTPException(status_code=404, detail="图片不存在。")
        thumbnail_path = pipeline_app.create_image_thumbnail(image_path)
        if not thumbnail_path:
            return FileResponse(image_path, media_type=media_type_for_path(image_path))
        thumbnail_file = Path(thumbnail_path)
        return FileResponse(
            thumbnail_file,
            media_type=media_type_for_path(thumbnail_file) or "image/webp",
        )

    root = project_root()
    user_dir = root / "platform_frontend" / "user"
    admin_dir = root / "platform_frontend" / "admin"
    if user_dir.exists():
        app.mount("/user", StaticFiles(directory=str(user_dir), html=True), name="user")
    if admin_dir.exists() and not CONFIG.desktop_user_only:
        app.mount("/admin", StaticFiles(directory=str(admin_dir), html=True), name="admin")

    @app.get("/favicon.ico")
    def favicon() -> FileResponse:
        icon_path = user_dir / "datadog.svg"
        if not icon_path.exists():
            raise HTTPException(status_code=404, detail="图标不存在。")
        return FileResponse(icon_path, media_type="image/svg+xml")

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse("/user/")

    return app


app = create_app()
