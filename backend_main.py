#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import platform
import sys
import threading
from pathlib import Path

import uvicorn

from api_server import APP_TITLE, create_api_server


def env_path(name: str, default: Path) -> Path:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    return Path(raw_value).expanduser().resolve()


def configure_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def install_global_exception_logging() -> None:
    def log_uncaught_exception(exc_type, exc, tb) -> None:
        logging.critical(
            "uncaught backend exception",
            exc_info=(exc_type, exc, tb),
        )

    sys.excepthook = log_uncaught_exception

    if hasattr(threading, "excepthook"):
        original_threading_excepthook = threading.excepthook

        def log_thread_exception(args) -> None:
            logging.critical(
                "uncaught backend thread exception thread=%s",
                getattr(args.thread, "name", ""),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            original_threading_excepthook(args)

        threading.excepthook = log_thread_exception


def log_runtime_diagnostics(project_root: Path, asset_root: Path, port: int) -> None:
    backend_exe_dir = asset_root / "backend-exe"
    web_dir = asset_root / "web"
    logging.info(
        "runtime diagnostics pid=%s executable=%s cwd=%s frozen=%s platform=%s python=%s",
        os.getpid(),
        sys.executable,
        Path.cwd(),
        getattr(sys, "frozen", False),
        platform.platform(),
        sys.version.replace("\n", " "),
    )
    logging.info(
        "runtime diagnostics env port=%s project_root_exists=%s asset_root_exists=%s web_exists=%s backend_exe_dir_exists=%s",
        port,
        project_root.exists(),
        asset_root.exists(),
        web_dir.exists(),
        backend_exe_dir.exists(),
    )
    logging.info(
        "runtime diagnostics paths project_root=%s asset_root=%s web_dir=%s backend_exe_dir=%s",
        project_root,
        asset_root,
        web_dir,
        backend_exe_dir,
    )


class StartupLoggingServer(uvicorn.Server):
    async def startup(self, sockets=None) -> None:
        logging.info("uvicorn startup begin")
        try:
            await super().startup(sockets=sockets)
        except Exception:
            logging.exception("uvicorn startup failed")
            raise
        logging.info(
            "uvicorn startup completed started=%s should_exit=%s",
            self.started,
            self.should_exit,
        )


def configure_windows_event_loop() -> None:
    if sys.platform != "win32":
        return
    try:
        import asyncio

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        logging.info("using WindowsSelectorEventLoopPolicy")
    except Exception as exc:
        logging.warning("failed to set Windows selector event loop policy: %s", exc)


def schedule_backend_self_check(port: int) -> None:
    def worker() -> None:
        import time
        import urllib.error
        import urllib.request

        url = f"http://127.0.0.1:{port}/api/health"
        for attempt in range(1, 61):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    body = response.read(200).decode("utf-8", errors="replace")
                logging.info(
                    "backend self-check ok attempt=%s status=%s body=%s",
                    attempt,
                    getattr(response, "status", ""),
                    body,
                )
                return
            except Exception as exc:
                if attempt in {1, 10, 30, 60}:
                    logging.info(
                        "backend self-check pending attempt=%s error=%s",
                        attempt,
                        exc,
                    )

    threading.Thread(target=worker, name="backend-self-check", daemon=True).start()


def main() -> int:
    current_dir = Path(__file__).resolve().parent
    project_root = env_path("IMAG_REPLICATE2_PROJECT_ROOT", current_dir)
    asset_root = env_path("IMAG_REPLICATE2_ASSET_ROOT", current_dir)
    port = int(os.environ.get("IMAG_REPLICATE2_PORT", "18789"))
    log_file = project_root / "logs" / "backend-server.log"
    try:
        configure_logging(log_file)
    except OSError:
        fallback_root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_TITLE
        project_root = fallback_root
        log_file = project_root / "logs" / "backend-server.log"
        configure_logging(log_file)
    install_global_exception_logging()

    logging.info("%s backend starting on port %s", APP_TITLE, port)
    logging.info("project_root=%s", project_root)
    logging.info("asset_root=%s", asset_root)
    log_runtime_diagnostics(project_root, asset_root, port)
    configure_windows_event_loop()

    try:
        logging.info("creating FastAPI app")
        app = create_api_server(project_root=project_root, asset_root=asset_root)
        logging.info("FastAPI app created")
    except Exception:
        logging.exception("FastAPI app creation failed")
        return 1
    logging.info("configuring uvicorn")
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        loop="none",
        http="h11",
        ws="none",
        lifespan="off",
        log_config=None,
        log_level="warning",
        access_log=False,
    )
    server = StartupLoggingServer(config)
    server.install_signal_handlers = lambda: None
    logging.info("starting uvicorn")
    schedule_backend_self_check(port)
    try:
        server.run()
    except Exception:
        logging.exception("uvicorn run failed")
        return 1
    logging.info("uvicorn stopped")
    if not server.started:
        logging.error("uvicorn stopped before startup completed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
