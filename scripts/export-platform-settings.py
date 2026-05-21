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
from api_server import SECRET_SETTING_KEYS, validate_settings  # noqa: E402
from platform_backend.app.config import CONFIG  # noqa: E402
from platform_backend.app.database import json_loads  # noqa: E402


SECRET_KEYS = set(SECRET_SETTING_KEYS)
SETTING_KEYS = {item.name for item in fields(pipeline_core.Settings)}
GLOBAL_SETTINGS_KEY = "default"


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _load_user_settings(conn: sqlite3.Connection, username: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if username:
        row = conn.execute(
            """
            SELECT users.id, users.username, user_settings.payload_json, user_settings.updated_at
            FROM users
            JOIN user_settings ON user_settings.user_id = users.id
            WHERE users.username = ?
            """,
            (username,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT users.id, users.username, user_settings.payload_json, user_settings.updated_at
            FROM user_settings
            JOIN users ON users.id = user_settings.user_id
            ORDER BY user_settings.updated_at DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return {}, {}
    payload = json_loads(row["payload_json"], {})
    if not isinstance(payload, dict):
        payload = {}
    settings = {
        key: value
        for key, value in payload.items()
        if key in SETTING_KEYS and key not in SECRET_KEYS
    }
    return settings, {
        "user_id": row["id"],
        "username": row["username"],
        "user_settings_updated_at": row["updated_at"],
    }


def _global_updated_at(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT updated_at FROM global_settings WHERE key = ?",
        (GLOBAL_SETTINGS_KEY,),
    ).fetchone()
    return str(row["updated_at"] or "") if row else ""


def _read_json(path: Path) -> dict[str, Any]:
    payload = pipeline_core.read_json_file(path, {})
    return payload if isinstance(payload, dict) else {}


def _seed_settings() -> dict[str, Any]:
    default_payload = pipeline_core.Settings.from_dict(
        _read_json(ROOT / "config.example.json")
    ).to_dict()
    if not CONFIG.original_config_path.exists():
        return validate_settings(pipeline_core.Settings.from_dict(default_payload)).to_dict()
    raw_payload = _read_json(CONFIG.original_config_path)
    merged = pipeline_core.merge_seed_settings_payload(
        raw_payload=raw_payload,
        default_payload=default_payload,
    )
    return validate_settings(pipeline_core.Settings.from_dict(merged)).to_dict()


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


def _load_global_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    seed_payload = _seed_settings()
    row = conn.execute(
        "SELECT payload_json FROM global_settings WHERE key = ?",
        (GLOBAL_SETTINGS_KEY,),
    ).fetchone()
    if not row:
        return dict(seed_payload)
    raw_payload = json_loads(row["payload_json"], {})
    if not isinstance(raw_payload, dict):
        raw_payload = {}
    merged = pipeline_core.merge_seed_settings_payload(
        raw_payload=raw_payload,
        default_payload=seed_payload,
    )
    return validate_settings(pipeline_core.Settings.from_dict(merged)).to_dict()


def _split_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    settings: dict[str, Any] = {}
    secrets: dict[str, str] = {}
    for key, value in payload.items():
        if key not in SETTING_KEYS:
            continue
        if key in SECRET_KEYS:
            text = str(value or "").strip()
            if text and text != "replace-me":
                secrets[key] = text
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

    user_settings: dict[str, Any] = {}
    user_source: dict[str, Any] = {}

    with _connect(db_path) as conn:
        global_payload = _load_global_settings(conn)
        global_settings, global_secrets = _split_payload(global_payload)
        global_updated_at = _global_updated_at(conn)
        if not args.global_only:
            user_settings, user_source = _load_user_settings(conn, args.username)

    merged_settings = validate_settings(
        pipeline_core.Settings.from_dict({**global_settings, **user_settings, **global_secrets})
    ).to_dict()
    settings, _ignored_secrets = _split_payload(merged_settings)

    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "database_path": str(db_path),
            "global_updated_at": global_updated_at,
            "non_secret_source": "global_settings" if args.global_only or not user_source else "user_effective_settings",
            "secret_source": "global_settings",
            **user_source,
        },
        "settings": settings,
        "secrets": global_secrets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export platform settings for server import.")
    parser.add_argument(
        "--config",
        default="",
        help="Read settings directly from a config.json file instead of the local platform database.",
    )
    parser.add_argument("--database", default="", help="SQLite database path. Defaults to PLATFORM_DATABASE_PATH.")
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
