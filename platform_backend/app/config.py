from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or name in os.environ:
            continue
        os.environ[name] = value.strip().strip('"').strip("'")


_load_dotenv()


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


DEFAULT_BASE_DIR = Path(_env("PLATFORM_BASE_DIR", "platform_runtime")).resolve()
DEFAULT_CONFIG_PATH = DEFAULT_BASE_DIR / "config.json"


@dataclass(frozen=True)
class PlatformConfig:
    app_name: str = "设计出图内部平台"
    base_dir: Path = DEFAULT_BASE_DIR
    original_config_path: Path = Path(
        _env("PLATFORM_CONFIG_PATH", str(DEFAULT_CONFIG_PATH))
    ).resolve()
    database_path: Path = Path(
        _env("PLATFORM_DATABASE_PATH", "platform_runtime/platform.db")
    ).resolve()
    storage_dir: Path = Path(_env("PLATFORM_STORAGE_DIR", "platform_runtime/storage")).resolve()
    server_host: str = _env("PLATFORM_HOST", "0.0.0.0")
    server_port: int = int(_env("PLATFORM_PORT", "8000"))
    session_cookie_name: str = _env("PLATFORM_SESSION_COOKIE", "design_output_session")
    session_days: int = int(_env("PLATFORM_SESSION_DAYS", "7"))
    session_cookie_secure: bool = _env("PLATFORM_COOKIE_SECURE", "0") == "1"
    app_secret: str = _env("PLATFORM_APP_SECRET", "change-this-secret-before-deploy")
    bootstrap_admin_username: str = _env("PLATFORM_ADMIN_USERNAME", "admin")
    bootstrap_admin_password: str = _env("PLATFORM_ADMIN_PASSWORD", "admin123456")
    max_upload_mb: int = int(_env("PLATFORM_MAX_UPLOAD_MB", "80"))
    history_retention_days: int = int(_env("PLATFORM_HISTORY_RETENTION_DAYS", "10"))
    log_retention_days: int = int(_env("PLATFORM_LOG_RETENTION_DAYS", "5"))
    history_cleanup_interval_hours: int = int(
        _env("PLATFORM_HISTORY_CLEANUP_INTERVAL_HOURS", "24")
    )
    worker_poll_seconds: float = float(_env("PLATFORM_WORKER_POLL_SECONDS", "2"))
    worker_concurrency: int = max(1, int(_env("PLATFORM_WORKER_CONCURRENCY", "100")))
    default_user_concurrent_limit: int = max(
        1,
        int(_env("PLATFORM_DEFAULT_USER_CONCURRENT_LIMIT", "30")),
    )
    max_user_concurrent_limit: int = max(
        1,
        int(_env("PLATFORM_MAX_USER_CONCURRENT_LIMIT", "100")),
    )
    pipeline_enabled: bool = _env("PLATFORM_ENABLE_PIPELINE", "1") == "1"
    desktop_mode: bool = _env("PLATFORM_DESKTOP_MODE", "0") == "1"
    desktop_user_only: bool = _env("PLATFORM_DESKTOP_USER_ONLY", "0") == "1"
    desktop_global_secrets: bool = _env("PLATFORM_DESKTOP_GLOBAL_SECRETS", "0") == "1"

    def ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)


CONFIG = PlatformConfig()
