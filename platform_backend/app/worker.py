from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import time
import threading

from .config import CONFIG
from .database import init_db
from .download_service import cleanup_old_downloads
from .pipeline_adapter import run_pipeline_job
from .storage_service import job_storage_dir, register_artifact
from .task_service import claim_next_job, cleanup_expired_job_history, cleanup_expired_logs, finish_job


def run_job(job: dict) -> None:
    job_id = job["id"]
    user_id = job["user_id"]
    if CONFIG.pipeline_enabled:
        result = run_pipeline_job(job)
        record = result.get("record") if isinstance(result.get("record"), dict) else {}
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        status = str(record.get("status") or summary.get("status") or "completed")
        error = str(record.get("error") or summary.get("error") or "")
        if status not in {"completed", "partial", "failed"}:
            status = "failed" if error else "completed"
        finish_job(
            job_id=job_id,
            user_id=user_id,
            status=status,
            result=result,
            error=error,
        )
        return

    output_dir = job_storage_dir(user_id, job_id) / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "result.txt"
    result_path.write_text(
        (
            "这是 Web 平台 Worker 的任务执行占位产物。\n"
            "下一步可在这里接入现有 pipeline_core 的具体生图流程。\n"
            f"task_type={job['task_type']}\n"
        ),
        encoding="utf-8",
    )
    artifact = register_artifact(
        job_id=job_id,
        user_id=user_id,
        kind="diagnostic",
        path=result_path,
        url=f"/api/v1/files/{user_id}/jobs/{job_id}/outputs/{result_path.name}",
        mime_type="text/plain",
    )
    finish_job(
        job_id=job_id,
        user_id=user_id,
        status="completed",
        result={
            "message": "任务骨架已跑通，pipeline_core 接入点已预留。",
            "artifacts": [artifact],
        },
    )


def run_forever(
    stop_event: threading.Event | None = None,
    *,
    initialize: bool = True,
) -> None:
    if initialize:
        init_db()
    CONFIG.ensure_dirs()
    cleanup_old_downloads()
    cleanup_expired_job_history(retention_days=CONFIG.history_retention_days)
    cleanup_expired_logs(retention_days=CONFIG.log_retention_days)
    cleanup_interval_seconds = max(3600, int(CONFIG.history_cleanup_interval_hours) * 3600)
    last_cleanup = time.monotonic()
    max_workers = max(1, int(CONFIG.worker_concurrency))
    futures = {}

    def run_job_safely(job: dict) -> None:
        try:
            run_job(job)
        except Exception as exc:
            finish_job(
                job_id=job["id"],
                user_id=job["user_id"],
                status="failed",
                result={},
                error=str(exc),
                progress=100,
            )

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="platform-worker") as executor:
        while True:
            if time.monotonic() - last_cleanup >= cleanup_interval_seconds:
                cleanup_old_downloads()
                cleanup_expired_job_history(retention_days=CONFIG.history_retention_days)
                cleanup_expired_logs(retention_days=CONFIG.log_retention_days)
                last_cleanup = time.monotonic()

            should_stop = bool(stop_event and stop_event.is_set())
            while not should_stop and len(futures) < max_workers:
                job = claim_next_job()
                if not job:
                    break
                futures[executor.submit(run_job_safely, job)] = job

            if should_stop and not futures:
                break

            if futures:
                done, _pending = wait(
                    futures,
                    timeout=CONFIG.worker_poll_seconds,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    futures.pop(future, None)
                    future.result()
                continue

            if stop_event:
                stop_event.wait(CONFIG.worker_poll_seconds)
            else:
                time.sleep(CONFIG.worker_poll_seconds)


if __name__ == "__main__":
    run_forever()
