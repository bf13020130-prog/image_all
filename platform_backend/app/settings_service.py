from __future__ import annotations

import shutil
from dataclasses import fields
from pathlib import Path
from typing import Any

import pipeline_core as pipeline_app
from settings_contract import (
    POOL_SECRET_SETTING_KEYS as ORIGINAL_POOL_SECRET_SETTING_KEYS,
    SECRET_SETTING_KEYS as ORIGINAL_SECRET_SETTING_KEYS,
    merge_preserved_pool_secrets,
    merge_preserved_secret_settings,
    settings_payload,
    validate_settings,
)

from .config import CONFIG
from .database import connect, json_dumps, json_loads
from .security import decrypt_secret, encrypt_secret, mask_secret, utc_now


GLOBAL_SETTINGS_KEY = "default"
SECRET_KEYS = tuple(ORIGINAL_SECRET_SETTING_KEYS)
POOL_SECRET_KEYS = tuple(ORIGINAL_POOL_SECRET_SETTING_KEYS)
SIMPLE_SECRET_KEYS = tuple(key for key in SECRET_KEYS if key not in POOL_SECRET_KEYS)
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
    return _normalize_settings(default_payload)


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


def _pool_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _secret_value_saved(key: str, value: Any) -> bool:
    if key in POOL_SECRET_KEYS:
        return any(
            bool(pipeline_app.resolve_secret_value(item.get("api_key")))
            for item in _pool_items(value)
        )
    text = str(value or "").strip()
    return bool(text and text != "replace-me")


def _secret_value_masked(key: str, value: Any) -> Any:
    if key in POOL_SECRET_KEYS:
        return pipeline_app.pool_with_public_secrets(_pool_items(value))
    text = str(value or "").strip()
    return mask_secret(text) if text and text != "replace-me" else ""


def _secret_status_mask(key: str, value: Any) -> str:
    if key in POOL_SECRET_KEYS:
        count = sum(
            1
            for item in _pool_items(value)
            if pipeline_app.resolve_secret_value(item.get("api_key"))
        )
        return f"已配置 {count} 个 Key" if count else ""
    masked = _secret_value_masked(key, value)
    return str(masked or "")


def _empty_secret_value(key: str) -> Any:
    return [] if key in POOL_SECRET_KEYS else ""


def _deserialize_secret_value(key: str, encrypted_value: str) -> Any:
    value = decrypt_secret(encrypted_value)
    if key not in POOL_SECRET_KEYS:
        return value
    parsed = json_loads(value, [])
    return parsed if isinstance(parsed, list) else []


def _serialize_secret_value(key: str, value: Any) -> str:
    if key in POOL_SECRET_KEYS:
        return json_dumps(_pool_items(value))
    return str(value or "").strip()


def _merge_incoming_secret_value(key: str, incoming: Any, current: Any) -> Any:
    if key in POOL_SECRET_KEYS:
        return merge_preserved_pool_secrets(incoming, current)
    value = str(incoming or "").strip()
    if pipeline_app.is_masked_secret_value(value):
        current_value = str(current or "").strip()
        return current_value if current_value else None
    return value


SETTINGS_JSON_SCHEMA_VERSION = 1


def _is_settings_json_document(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("schema_version") == SETTINGS_JSON_SCHEMA_VERSION
        and isinstance(payload.get("global"), dict)
        and isinstance(payload.get("users"), dict)
    )


def _split_settings_and_secrets(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    settings: dict[str, Any] = {}
    secrets: dict[str, Any] = {}
    for key, value in (payload or {}).items():
        if key not in SETTING_KEYS:
            continue
        if key in SECRET_KEYS:
            if _secret_value_saved(key, value):
                secrets[key] = value
            continue
        settings[key] = value
    return settings, secrets


def _encode_secret_values(values: dict[str, Any]) -> dict[str, str]:
    encoded: dict[str, str] = {}
    for key in SECRET_KEYS:
        if key not in values or not _secret_value_saved(key, values.get(key)):
            continue
        encoded[key] = encrypt_secret(_serialize_secret_value(key, values.get(key)))
    return encoded


def _decode_secret_values(values: Any) -> dict[str, Any]:
    if not isinstance(values, dict):
        return {}
    decoded: dict[str, Any] = {}
    for key, encrypted_value in values.items():
        if key not in SECRET_KEYS:
            continue
        decoded[key] = _deserialize_secret_value(key, str(encrypted_value or ""))
    return decoded


def _settings_json_path() -> Path:
    return CONFIG.original_config_path


def _write_settings_json_document(document: dict[str, Any]) -> None:
    pipeline_app.write_json(_settings_json_path(), document)


def _backup_legacy_settings_json(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    stamp = utc_now().replace("-", "").replace(":", "").replace("Z", "")
    backup_path = path.with_name(f"{path.name}.legacy-{stamp}.bak")
    shutil.copy2(path, backup_path)


def _legacy_global_payload_from_db(seed_payload: dict[str, Any]) -> dict[str, Any]:
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


def _legacy_user_blocks_from_db() -> dict[str, dict[str, Any]]:
    users: dict[str, dict[str, Any]] = {}
    with connect() as conn:
        for row in conn.execute("SELECT user_id, payload_json FROM user_settings").fetchall():
            payload = json_loads(row["payload_json"], {})
            if not isinstance(payload, dict):
                payload = {}
            users.setdefault(str(row["user_id"]), {})["settings"] = _clean_settings_payload(payload)
        for row in conn.execute(
            "SELECT user_id, secret_key, encrypted_value FROM user_secrets"
        ).fetchall():
            key = str(row["secret_key"])
            if key not in SECRET_KEYS:
                continue
            user_id = str(row["user_id"])
            users.setdefault(user_id, {}).setdefault("secrets", {})[key] = (
                _deserialize_secret_value(key, row["encrypted_value"])
            )
    return users


def _new_settings_json_document(
    *,
    global_payload: dict[str, Any],
    user_blocks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    now = utc_now()
    global_settings, global_secrets = _split_settings_and_secrets(global_payload)
    users: dict[str, dict[str, Any]] = {}
    for user_id, block in user_blocks.items():
        user_settings = _clean_settings_payload(block.get("settings", {}))
        user_secrets = {
            key: value
            for key, value in (block.get("secrets", {}) or {}).items()
            if key in SECRET_KEYS and _secret_value_saved(key, value)
        }
        users[user_id] = {
            "settings": user_settings,
            "secrets": _encode_secret_values(user_secrets),
            "updated_at": now,
        }
    return {
        "schema_version": SETTINGS_JSON_SCHEMA_VERSION,
        "updated_at": now,
        "global": {
            "settings": global_settings,
            "secrets": _encode_secret_values(global_secrets),
            "updated_at": now,
        },
        "users": users,
    }


def _migrate_settings_json_document(raw_payload: dict[str, Any]) -> dict[str, Any]:
    seed_payload = _seed_settings()
    legacy_seed = seed_payload
    if raw_payload:
        legacy_seed = _normalize_settings(
            pipeline_app.merge_seed_settings_payload(
                raw_payload=raw_payload,
                default_payload=seed_payload,
            )
        )
    global_payload = _legacy_global_payload_from_db(legacy_seed)
    document = _new_settings_json_document(
        global_payload=global_payload,
        user_blocks=_legacy_user_blocks_from_db(),
    )
    path = _settings_json_path()
    if path.exists() and raw_payload:
        _backup_legacy_settings_json(path)
    _write_settings_json_document(document)
    return document


def _settings_json_document() -> dict[str, Any]:
    raw_payload = _read_json(_settings_json_path())
    if _is_settings_json_document(raw_payload):
        return raw_payload
    return _migrate_settings_json_document(raw_payload if isinstance(raw_payload, dict) else {})


def _global_payload_from_document(document: dict[str, Any]) -> dict[str, Any]:
    global_block = document.get("global") if isinstance(document.get("global"), dict) else {}
    settings = global_block.get("settings") if isinstance(global_block.get("settings"), dict) else {}
    secrets = _decode_secret_values(global_block.get("secrets"))
    seed_payload = _seed_settings()
    merged = pipeline_app.merge_seed_settings_payload(
        raw_payload={**settings, **secrets},
        default_payload=seed_payload,
    )
    return _normalize_settings(_backfill_old_platform_defaults(merged, seed_payload))


def _user_block(document: dict[str, Any], user_id: str) -> dict[str, Any]:
    users = document.setdefault("users", {})
    if not isinstance(users, dict):
        users = {}
        document["users"] = users
    block = users.setdefault(user_id, {})
    if not isinstance(block, dict):
        block = {}
        users[user_id] = block
    block.setdefault("settings", {})
    block.setdefault("secrets", {})
    return block


def public_settings_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return settings_payload(validate_settings(pipeline_app.Settings.from_dict(payload)))


def get_global_settings() -> dict[str, Any]:
    return _global_payload_from_document(_settings_json_document())


def get_public_global_settings() -> dict[str, Any]:
    return public_settings_payload(get_global_settings())


def get_global_secret_status() -> dict[str, dict[str, Any]]:
    settings = get_global_settings()
    status: dict[str, dict[str, Any]] = {}
    for key in SECRET_KEYS:
        value = settings.get(key)
        saved = _secret_value_saved(key, value)
        status[key] = {
            "saved": saved,
            "masked": _secret_status_mask(key, value) if saved else "",
        }
    return status


def get_admin_global_settings(*, reveal_secrets: bool = False) -> dict[str, Any]:
    settings = get_global_settings()
    payload = public_settings_payload(settings)
    payload["_secret_keys"] = list(SECRET_KEYS)
    payload["_secret_status"] = get_global_secret_status()
    for key in SIMPLE_SECRET_KEYS:
        if str(settings.get(key) or "") == "replace-me":
            payload[key] = ""
    if reveal_secrets:
        for key in SECRET_KEYS:
            value = settings.get(key)
            if key in POOL_SECRET_KEYS:
                payload[key] = _pool_items(value)
            else:
                text = str(value or "")
                payload[key] = "" if text == "replace-me" else text
    return payload


def _user_uses_global_secrets(user_id: str) -> bool:
    if CONFIG.desktop_global_secrets:
        return True
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
        cleaned[key] = _empty_secret_value(key)
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
        return CONFIG.default_user_concurrent_limit
    return max(1, int(row["concurrent_limit"] or CONFIG.default_user_concurrent_limit))


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
    document = _settings_json_document()
    settings, secrets = _split_settings_and_secrets(normalized)
    document["global"] = {
        "settings": settings,
        "secrets": _encode_secret_values(secrets),
        "updated_at": now,
        "updated_by": actor_id,
    }
    document["updated_at"] = now
    _write_settings_json_document(document)
    return normalized


def get_user_settings(user_id: str) -> dict[str, Any]:
    document = _settings_json_document()
    users = document.get("users") if isinstance(document.get("users"), dict) else {}
    block = users.get(user_id) if isinstance(users.get(user_id), dict) else {}
    payload = block.get("settings") if isinstance(block.get("settings"), dict) else {}
    return _clean_settings_payload(payload)


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
    document = _settings_json_document()
    block = _user_block(document, user_id)
    block["settings"] = settings_payload_clean
    block["updated_at"] = now
    document["updated_at"] = now
    _write_settings_json_document(document)
    return settings_payload_clean


def get_user_secrets(user_id: str, *, reveal: bool = False) -> dict[str, Any]:
    document = _settings_json_document()
    users = document.get("users") if isinstance(document.get("users"), dict) else {}
    block = users.get(user_id) if isinstance(users.get(user_id), dict) else {}
    secrets = _decode_secret_values(block.get("secrets") if isinstance(block, dict) else {})
    result: dict[str, Any] = {}
    for key, value in secrets.items():
        result[key] = value if reveal else _secret_value_masked(key, value)
    return result


def get_user_secret_status(user_id: str) -> dict[str, dict[str, Any]]:
    global_status = get_global_secret_status() if _user_uses_global_secrets(user_id) else {}
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
    document = _settings_json_document()
    users = document.get("users") if isinstance(document.get("users"), dict) else {}
    block = users.get(user_id) if isinstance(users.get(user_id), dict) else {}
    updated_at = str(block.get("updated_at") or "") if isinstance(block, dict) else ""
    secrets = _decode_secret_values(block.get("secrets") if isinstance(block, dict) else {})
    for key, value in secrets.items():
        if key not in SECRET_KEYS:
            continue
        saved = _secret_value_saved(key, value)
        status[key] = {
            "saved": saved,
            "masked": _secret_status_mask(key, value) if saved else "",
            "updated_at": updated_at,
            "default_saved": bool(global_status.get(key, {}).get("saved")),
            "default_masked": str(global_status.get(key, {}).get("masked") or ""),
            "effective_source": "user" if saved else (
                "global" if global_status.get(key, {}).get("saved") else "empty"
            ),
        }
    return status


def save_user_secrets(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    current_values = get_user_secrets(user_id, reveal=True)
    next_values = dict(current_values)
    for key in SECRET_KEYS:
        if key not in payload:
            continue
        value = _merge_incoming_secret_value(
            key,
            payload.get(key),
            current_values.get(key),
        )
        if value is None or not _secret_value_saved(key, value):
            next_values.pop(key, None)
            continue
        next_values[key] = value
    document = _settings_json_document()
    block = _user_block(document, user_id)
    block["secrets"] = _encode_secret_values(next_values)
    block["updated_at"] = now
    document["updated_at"] = now
    _write_settings_json_document(document)
    return get_user_secrets(user_id, reveal=False)


def delete_user_settings(user_id: str) -> bool:
    document = _settings_json_document()
    users = document.get("users") if isinstance(document.get("users"), dict) else {}
    if user_id not in users:
        return False
    users.pop(user_id, None)
    document["users"] = users
    document["updated_at"] = utc_now()
    _write_settings_json_document(document)
    return True


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
        public_settings_payload(global_settings),
    )
    public_effective = _public_with_user_concurrency_limit(
        user_id,
        public_settings_payload(effective_settings),
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
