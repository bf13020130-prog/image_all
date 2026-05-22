from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any

import pipeline_core as pipeline_app
from api_server import (
    SECRET_SETTING_KEYS as ORIGINAL_SECRET_SETTING_KEYS,
    merge_preserved_secret_settings,
    settings_payload,
    validate_settings,
)

from .config import CONFIG
from .database import connect, json_dumps, json_loads, transaction
from .security import decrypt_secret, encrypt_secret, mask_secret, utc_now


GLOBAL_SETTINGS_KEY = "default"
SECRET_KEYS = tuple(ORIGINAL_SECRET_SETTING_KEYS)
SETTING_KEYS = {item.name for item in fields(pipeline_app.Settings)}

OLD_PLATFORM_DEFAULTS: dict[str, Any] = {
    "default_concurrency": 3,
    "system_prompt": "你是一名商业美妆静物提示词生成器。",
    "default_user_prompt": "请根据参考图生成商业静物广告图提示词。",
    "style_replicate2_system_prompt": "你是商业静物图像风格复刻提示词专家。",
    "style_replicate2_user_prompt": "请根据参考图生成新的商业静物广告场景。",
    "image_agent_planner_prompt": "你是图片生成规划助手，请判断用户是否需要生成图片并规划交付项。",
    "image_agent_creator_prompt": "你是商业图片创作助手，请把规划转成可执行的英文生图提示词。",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    payload = pipeline_app.read_json_file(path, {})
    return payload if isinstance(payload, dict) else {}


def _normalize_settings(payload: dict[str, Any]) -> dict[str, Any]:
    return validate_settings(pipeline_app.Settings.from_dict(payload)).to_dict()


def _seed_settings() -> dict[str, Any]:
    root = _project_root()
    example_path = root / "config.example.json"
    default_payload = pipeline_app.Settings.from_dict(_read_json(example_path)).to_dict()
    config_path = CONFIG.original_config_path
    if not config_path.exists():
        return _normalize_settings(default_payload)
    raw_payload = _read_json(config_path)
    merged = pipeline_app.merge_seed_settings_payload(
        raw_payload=raw_payload,
        default_payload=default_payload,
    )
    return _normalize_settings(merged)


def _backfill_old_platform_defaults(
    payload: dict[str, Any],
    seed_payload: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(payload)
    for key, old_value in OLD_PLATFORM_DEFAULTS.items():
        if key in seed_payload and merged.get(key) == old_value:
            merged[key] = seed_payload[key]
    return merged


def _clean_settings_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in (payload or {}).items()
        if key in SETTING_KEYS and key not in SECRET_KEYS
    }


def public_settings_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return settings_payload(validate_settings(pipeline_app.Settings.from_dict(payload)))


def get_global_settings() -> dict[str, Any]:
    seed_payload = _seed_settings()
    with connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM global_settings WHERE key = ?",
            (GLOBAL_SETTINGS_KEY,),
        ).fetchone()
    if not row:
        return dict(seed_payload)
    raw_payload = json_loads(row["payload_json"], {})
    if not isinstance(raw_payload, dict):
        raw_payload = {}
    merged = pipeline_app.merge_seed_settings_payload(
        raw_payload=raw_payload,
        default_payload=seed_payload,
    )
    return _normalize_settings(_backfill_old_platform_defaults(merged, seed_payload))


def get_public_global_settings() -> dict[str, Any]:
    return public_settings_payload(get_global_settings())


def get_global_secret_status() -> dict[str, dict[str, Any]]:
    settings = get_global_settings()
    status: dict[str, dict[str, Any]] = {}
    for key in SECRET_KEYS:
        value = str(settings.get(key) or "")
        saved = bool(value and value != "replace-me")
        status[key] = {
            "saved": saved,
            "masked": mask_secret(value) if saved else "",
        }
    return status


def get_admin_global_settings(*, reveal_secrets: bool = False) -> dict[str, Any]:
    settings = get_global_settings()
    payload = public_settings_payload(settings)
    payload["_secret_keys"] = list(SECRET_KEYS)
    payload["_secret_status"] = get_global_secret_status()
    for key in SECRET_KEYS:
        if str(settings.get(key) or "") == "replace-me":
            payload[key] = ""
    if reveal_secrets:
        for key in SECRET_KEYS:
            value = str(settings.get(key) or "")
            payload[key] = "" if value == "replace-me" else value
    return payload


def _user_uses_global_secrets(user_id: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["role"] == "admin")


def _global_settings_for_user(user_id: str) -> dict[str, Any]:
    settings = get_global_settings()
    if _user_uses_global_secrets(user_id):
        return settings
    return _without_secret_values(settings)


def _without_secret_values(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(payload)
    for key in SECRET_KEYS:
        cleaned[key] = ""
    return cleaned


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def get_user_concurrency_limit(user_id: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT concurrent_limit FROM user_quotas WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return 20
    return max(1, int(row["concurrent_limit"] or 20))


def _clamp_user_concurrency(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    limit = get_user_concurrency_limit(user_id)
    normalized = dict(payload)
    if "default_concurrency" in normalized:
        normalized["default_concurrency"] = _bounded_int(
            normalized.get("default_concurrency"),
            default=limit,
            minimum=1,
            maximum=limit,
        )
    return normalized


def _public_with_user_concurrency_limit(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    limit = get_user_concurrency_limit(user_id)
    public_payload = _clamp_user_concurrency(user_id, payload)
    public_payload["max_shared_concurrency"] = limit
    if "default_concurrency" not in public_payload:
        public_payload["default_concurrency"] = limit
    return public_payload


def save_global_settings(payload: dict[str, Any], actor_id: str | None = None) -> dict[str, Any]:
    current_payload = get_global_settings()
    current_settings = pipeline_app.Settings.from_dict(current_payload)
    incoming = {
        key: value
        for key, value in (payload or {}).items()
        if key in SETTING_KEYS
    }
    merged = merge_preserved_secret_settings(
        {**current_payload, **incoming},
        current_settings,
    )
    normalized = _normalize_settings(merged)
    now = utc_now()
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO global_settings (key, payload_json, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              payload_json = excluded.payload_json,
              updated_at = excluded.updated_at,
              updated_by = excluded.updated_by
            """,
            (GLOBAL_SETTINGS_KEY, json_dumps(normalized), now, actor_id),
        )
    return normalized


def get_user_settings(user_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return {}
    payload = json_loads(row["payload_json"], {})
    return _clean_settings_payload(payload) if isinstance(payload, dict) else {}


def save_user_settings(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    settings_payload_clean = _clean_settings_payload(payload)
    settings_payload_clean = _clamp_user_concurrency(user_id, settings_payload_clean)
    current_secrets = get_user_secrets(user_id, reveal=True)
    _normalize_settings(
        {
            **_global_settings_for_user(user_id),
            **settings_payload_clean,
            **current_secrets,
        }
    )
    now = utc_now()
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO user_settings (user_id, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              payload_json = excluded.payload_json,
              updated_at = excluded.updated_at
            """,
            (user_id, json_dumps(settings_payload_clean), now, now),
        )
    return settings_payload_clean


def get_user_secrets(user_id: str, *, reveal: bool = False) -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT secret_key, encrypted_value FROM user_secrets WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    result: dict[str, str] = {}
    for row in rows:
        if row["secret_key"] not in SECRET_KEYS:
            continue
        value = decrypt_secret(row["encrypted_value"])
        result[row["secret_key"]] = value if reveal else mask_secret(value)
    return result


def get_user_secret_status(user_id: str) -> dict[str, dict[str, Any]]:
    global_status = get_global_secret_status() if _user_uses_global_secrets(user_id) else {}
    with connect() as conn:
        rows = conn.execute(
            "SELECT secret_key, encrypted_value, updated_at FROM user_secrets WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    status = {
        key: {
            "saved": False,
            "masked": "",
            "updated_at": "",
            "default_saved": bool(global_status.get(key, {}).get("saved")),
            "default_masked": str(global_status.get(key, {}).get("masked") or ""),
            "effective_source": "global" if global_status.get(key, {}).get("saved") else "empty",
        }
        for key in SECRET_KEYS
    }
    for row in rows:
        key = row["secret_key"]
        if key not in SECRET_KEYS:
            continue
        value = decrypt_secret(row["encrypted_value"])
        status[key] = {
            "saved": bool(value),
            "masked": mask_secret(value),
            "updated_at": row["updated_at"],
            "default_saved": bool(global_status.get(key, {}).get("saved")),
            "default_masked": str(global_status.get(key, {}).get("masked") or ""),
            "effective_source": "user" if value else (
                "global" if global_status.get(key, {}).get("saved") else "empty"
            ),
        }
    return status


def save_user_secrets(user_id: str, payload: dict[str, Any]) -> dict[str, str]:
    now = utc_now()
    with transaction() as conn:
        for key in SECRET_KEYS:
            if key not in payload:
                continue
            value = str(payload.get(key) or "").strip()
            if not value:
                conn.execute(
                    "DELETE FROM user_secrets WHERE user_id = ? AND secret_key = ?",
                    (user_id, key),
                )
                continue
            conn.execute(
                """
                INSERT INTO user_secrets (user_id, secret_key, encrypted_value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, secret_key) DO UPDATE SET
                  encrypted_value = excluded.encrypted_value,
                  updated_at = excluded.updated_at
                """,
                (user_id, key, encrypt_secret(value), now),
            )
    return get_user_secrets(user_id, reveal=False)


def effective_settings_for_user(user_id: str) -> dict[str, Any]:
    normalized = _normalize_settings(
        {
            **_global_settings_for_user(user_id),
            **get_user_settings(user_id),
            **get_user_secrets(user_id, reveal=True),
        }
    )
    return _clamp_user_concurrency(user_id, normalized)


def public_settings_for_user(user_id: str) -> dict[str, Any]:
    global_settings = _without_secret_values(get_global_settings())
    user_settings = get_user_settings(user_id)
    user_secrets = get_user_secrets(user_id, reveal=False)
    secret_status = get_user_secret_status(user_id)
    effective_settings = effective_settings_for_user(user_id)
    public_defaults = _public_with_user_concurrency_limit(
        user_id,
        _without_secret_values(public_settings_payload(global_settings)),
    )
    public_effective = _public_with_user_concurrency_limit(
        user_id,
        _without_secret_values(public_settings_payload(effective_settings)),
    )
    return {
        "defaults": public_defaults,
        "overrides": user_settings,
        "secrets": user_secrets,
        "secret_status": secret_status,
        "secret_keys": list(SECRET_KEYS),
        "effective": public_effective,
        "settings": public_effective,
    }
