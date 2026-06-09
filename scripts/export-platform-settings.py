from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pipeline_core  # noqa: E402
from settings_contract import (  # noqa: E402
    POOL_SECRET_SETTING_KEYS,
    SECRET_SETTING_KEYS,
    validate_settings,
)
from platform_backend.app.config import CONFIG  # noqa: E402
from platform_backend.app.settings_service import (  # noqa: E402
    get_global_settings,
    get_user_secrets,
    get_user_settings,
)


SECRET_KEYS = set(SECRET_SETTING_KEYS)
POOL_SECRET_KEYS = set(POOL_SECRET_SETTING_KEYS)
SETTING_KEYS = {item.name for item in fields(pipeline_core.Settings)}
GLOBAL_SETTINGS_KEY = "default"


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _load_user_source(conn: sqlite3.Connection, username: str | None) -> dict[str, Any]:
    if username:
        row = conn.execute(
            """
            SELECT users.id, users.username
            FROM users
            WHERE users.username = ?
            """,
            (username,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT users.id, users.username
            FROM users
            ORDER BY users.updated_at DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return {}
    return {
        "user_id": row["id"],
        "username": row["username"],
    }


def _legacy_global_updated_at(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT updated_at FROM global_settings WHERE key = ?",
        (GLOBAL_SETTINGS_KEY,),
    ).fetchone()
    return str(row["updated_at"] or "") if row else ""


def _read_json(path: Path) -> dict[str, Any]:
    payload = pipeline_core.read_json_file(path, {})
    return payload if isinstance(payload, dict) else {}


def _settings_json_updated_at() -> str:
    payload = _read_json(CONFIG.original_config_path)
    if payload.get("schema_version") != 1:
        return ""
    global_block = payload.get("global") if isinstance(payload.get("global"), dict) else {}
    return str(global_block.get("updated_at") or payload.get("updated_at") or "")


def _settings_from_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"config not found: {path}")
    default_payload = pipeline_core.Settings.from_dict(
        _read_json(ROOT / "config.example.json")
    ).to_dict()
    raw_payload = _read_json(path)
    merged = pipeline_core.merge_seed_settings_payload(
        raw_payload=raw_payload,
        default_payload=default_payload,
    )
    return validate_settings(pipeline_core.Settings.from_dict(merged)).to_dict()


def _exportable_secret_value(key: str, value: Any) -> Any:
    if key in POOL_SECRET_KEYS:
        if not isinstance(value, list):
            return []
        pool = []
        for item in value:
            if not isinstance(item, dict):
                continue
            api_key = pipeline_core.resolve_secret_value(item.get("api_key"))
            if api_key:
                pool.append(dict(item))
        return pool
    text = str(value or "").strip()
    return text if text and text != "replace-me" else ""


def _split_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    settings: dict[str, Any] = {}
    secrets: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in SETTING_KEYS:
            continue
        if key in SECRET_KEYS:
            secret_value = _exportable_secret_value(key, value)
            if secret_value:
                secrets[key] = secret_value
            continue
        settings[key] = value
    return settings, secrets


def export_settings(args: argparse.Namespace) -> dict[str, Any]:
    if args.config:
        config_path = Path(args.config).resolve()
        config_payload = _settings_from_config(config_path)
        settings, secrets = _split_payload(config_payload)
        return {
            "schema_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": {
                "config_path": str(config_path),
                "non_secret_source": "config_file",
                "secret_source": "config_file",
            },
            "settings": settings,
            "secrets": secrets,
        }

    db_path = Path(args.database or CONFIG.database_path).resolve()
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")

    user_source: dict[str, Any] = {}
    settings_updated_at = _settings_json_updated_at()
    legacy_updated_at = ""

    with _connect(db_path) as conn:
        legacy_updated_at = _legacy_global_updated_at(conn)
        if not args.global_only:
            user_source = _load_user_source(conn, args.username)

    global_payload = get_global_settings()
    global_settings, global_secrets = _split_payload(global_payload)
    user_settings: dict[str, Any] = {}
    user_secrets: dict[str, Any] = {}
    if not args.global_only and user_source.get("user_id"):
        user_id = str(user_source["user_id"])
        user_settings = get_user_settings(user_id)
        user_secrets = get_user_secrets(user_id, reveal=True)
        user_secrets = {
            key: value
            for key, value in user_secrets.items()
            if _exportable_secret_value(key, value)
        }
    effective_secrets = {**global_secrets, **user_secrets}
    merged_settings = validate_settings(
        pipeline_core.Settings.from_dict({**global_settings, **user_settings, **effective_secrets})
    ).to_dict()
    settings, _ignored_secrets = _split_payload(merged_settings)

    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "database_path": str(db_path),
            "settings_json_path": str(CONFIG.original_config_path),
            "global_updated_at": settings_updated_at or legacy_updated_at,
            "settings_json_updated_at": settings_updated_at,
            "legacy_global_updated_at": legacy_updated_at,
            "non_secret_source": "settings_json_global" if args.global_only or not user_source else "settings_json_user_effective_settings",
            "secret_source": "settings_json_global" if args.global_only or not user_secrets else "settings_json_user_effective_secrets",
            **user_source,
        },
        "settings": settings,
        "secrets": effective_secrets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export platform settings for server import.")
    parser.add_argument(
        "--config",
        default="",
        help="Read settings directly from a legacy/plain config.json file instead of live platform settings JSON.",
    )
    parser.add_argument(
        "--database",
        default="",
        help="SQLite database path for user lookup. Defaults to PLATFORM_DATABASE_PATH.",
    )
    parser.add_argument("--username", default="", help="Merge this user's non-secret settings into the export.")
    parser.add_argument("--global-only", action="store_true", help="Export only admin global defaults.")
    parser.add_argument(
        "--output",
        default="release/platform-settings-export.json",
        help="Output JSON path.",
    )
    args = parser.parse_args()
    args.username = args.username.strip() or None

    payload = export_settings(args)
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Exported settings to {output_path}")
    print(f"Non-secret source: {payload['source'].get('non_secret_source')}")
    if payload["source"].get("config_path"):
        print(f"Config source: {payload['source']['config_path']}")
    if payload["source"].get("username"):
        print(f"User overrides merged: {payload['source']['username']}")
    print(f"Secrets exported: {sum(1 for value in payload['secrets'].values() if value)}")


if __name__ == "__main__":
    main()
