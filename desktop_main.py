#!/usr/bin/env python3
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

from api_server import create_api_server


APP_TITLE = "imag_Replicate2"


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def asset_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def wait_for_server(url: str, timeout_seconds: int = 20) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"本地服务启动失败：{last_error}")


def candidate_browser_paths() -> list[Path]:
    candidates: list[Path] = []
    for name in ("msedge.exe", "msedge", "chrome.exe", "chrome"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    program_files = [
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ]
    for candidate in program_files:
        if candidate.exists():
            candidates.append(candidate)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        marker = str(candidate).lower()
        if marker not in seen:
            seen.add(marker)
            unique.append(candidate)
    return unique


def launch_browser_app(url: str) -> tuple[subprocess.Popen[str], Path]:
    profile_dir = project_root() / "data" / "browser-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    for browser_path in candidate_browser_paths():
        command = [
            str(browser_path),
            f"--app={url}",
            "--new-window",
            "--no-first-run",
            "--disable-session-crashed-bubble",
            "--disable-features=msEdgeSidebarV2",
            f"--user-data-dir={profile_dir}",
        ]
        try:
            process = subprocess.Popen(command)
            return process, profile_dir
        except OSError:
            continue
    shutil.rmtree(profile_dir, ignore_errors=True)
    raise RuntimeError("未找到可用的 Edge / Chrome 桌面浏览器。")


def main() -> int:
    root = project_root()
    assets = asset_root()
    port = find_free_port()
    health_url = f"http://127.0.0.1:{port}/api/health"
    app_url = f"http://127.0.0.1:{port}/"

    server_app = create_api_server(project_root=root, asset_root=assets)
    server = uvicorn.Server(
        uvicorn.Config(
            server_app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
    )

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    try:
        wait_for_server(health_url)
        browser_process, profile_dir = launch_browser_app(app_url)
        browser_process.wait()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"{APP_TITLE} 启动失败: {exc}", file=sys.stderr)
        return 1
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
