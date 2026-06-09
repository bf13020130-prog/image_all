from __future__ import annotations

from typing import Any

from fastapi import HTTPException

import pipeline_core as pipeline_app


APP_TITLE = "设计出图"

POOL_SECRET_SETTING_KEYS = (
    "llm_key_pool",
    "gpt_image_key_pool",
    "gpt_image_1k_key_pool",
    "gemini_image_key_pool",
)


SECRET_SETTING_KEYS = (
    "llm_api_key",
    "color_match_api_key",
    "image_agent_api_key",
    "image_api_key",
    "image_1k_api_key",
    "gpt_image_api_key",
    "gpt_image_1k_api_key",
    "gemini_image_api_key",
    *POOL_SECRET_SETTING_KEYS,
)


def validate_settings(settings: pipeline_app.Settings) -> pipeline_app.Settings:
    settings.llm_endpoint_type = pipeline_app.normalize_llm_endpoint_type(
        settings.llm_endpoint_type
    )
    settings.color_match_endpoint_type = pipeline_app.normalize_llm_endpoint_type(
        settings.color_match_endpoint_type
    )
    settings.image_agent_endpoint_type = pipeline_app.normalize_llm_endpoint_type(
        settings.image_agent_endpoint_type
    )
    if settings.llm_connect_timeout_seconds <= 0:
        raise HTTPException(status_code=400, detail="大模型连接超时必须大于 0。")
    if settings.image_connect_timeout_seconds <= 0:
        raise HTTPException(status_code=400, detail="生图连接超时必须大于 0。")
    if settings.default_prompt_count <= 0:
        raise HTTPException(status_code=400, detail="默认提示词数必须大于 0。")
    if settings.default_images_per_prompt <= 0:
        raise HTTPException(status_code=400, detail="默认生成次数必须大于 0。")
    if settings.default_concurrency <= 0:
        raise HTTPException(status_code=400, detail="共享并发池必须大于 0。")
    try:
        (
            settings.default_output_resolution,
            settings.default_output_aspect_ratio,
        ) = pipeline_app.parse_output_selection(
            output_resolution=settings.default_output_resolution,
            output_aspect_ratio=settings.default_output_aspect_ratio,
            legacy_output=settings.default_aspect_ratio,
        )
    except pipeline_app.AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    settings.default_aspect_ratio = pipeline_app.output_selection_to_legacy_value(
        settings.default_output_resolution,
        settings.default_output_aspect_ratio,
    )
    if settings.default_concurrency > pipeline_app.MAX_IMAGE_CONCURRENCY:
        raise HTTPException(
            status_code=400,
            detail=f"共享并发池不能超过 {pipeline_app.MAX_IMAGE_CONCURRENCY}。",
        )
    return settings


def settings_payload(settings: pipeline_app.Settings) -> dict[str, Any]:
    settings.llm_endpoint_type = pipeline_app.normalize_llm_endpoint_type(
        settings.llm_endpoint_type
    )
    settings.color_match_endpoint_type = pipeline_app.normalize_llm_endpoint_type(
        settings.color_match_endpoint_type
    )
    settings.image_agent_endpoint_type = pipeline_app.normalize_llm_endpoint_type(
        settings.image_agent_endpoint_type
    )
    return {
        **settings.to_public_dict(),
        "available_llm_endpoint_types": [
            {
                "value": pipeline_app.LLM_ENDPOINT_CHAT_COMPLETIONS,
                "label": "/v1/chat/completions",
            },
            {
                "value": pipeline_app.LLM_ENDPOINT_RESPONSES,
                "label": "/v1/responses",
            },
        ],
        "available_image_models": pipeline_app.image_model_choices(),
        "available_output_presets": pipeline_app.output_preset_choices(),
        "available_output_resolutions": pipeline_app.output_resolution_choices(),
        "available_output_aspect_ratios": pipeline_app.output_aspect_ratio_choices(),
        "limits": {
            "style_reference_max": pipeline_app.MAX_STYLE_REFERENCE_IMAGES,
            "product_reference_max": pipeline_app.MAX_PRODUCT_REFERENCE_IMAGES,
            "style_replicate2_reference_max": (
                pipeline_app.MAX_STYLE_REPLICATE2_REFERENCE_IMAGES
            ),
            "image_edit_input_max": pipeline_app.MAX_IMAGE_EDIT_INPUT_IMAGES,
            "agent_image_count_max": pipeline_app.MAX_IMAGE_AGENT_REQUEST_COUNT,
        },
        "image_model_capabilities": {
            model["value"]: {
                "allowed_resolutions": pipeline_app.image_agent_allowed_resolutions(
                    model["value"]
                ),
                "allowed_aspect_ratios": pipeline_app.image_agent_allowed_aspect_ratios(
                    model["value"]
                ),
                "requires_fixed_output": pipeline_app.is_nano_banana_model(
                    model["value"]
                ),
            }
            for model in pipeline_app.image_model_choices()
        },
        "max_shared_concurrency": pipeline_app.MAX_IMAGE_CONCURRENCY,
        "app_title": APP_TITLE,
    }


def merge_preserved_pool_secrets(
    incoming_pool: Any,
    current_pool: Any,
) -> list[dict[str, Any]]:
    if not isinstance(incoming_pool, list):
        return incoming_pool if isinstance(incoming_pool, list) else []
    current_items = (
        [item for item in current_pool if isinstance(item, dict)]
        if isinstance(current_pool, list)
        else []
    )
    current_by_id = {
        str(item.get("id") or "").strip(): item
        for item in current_items
        if str(item.get("id") or "").strip()
    }
    merged_pool: list[dict[str, Any]] = []
    for index, item in enumerate(incoming_pool):
        if not isinstance(item, dict):
            continue
        merged_item = dict(item)
        incoming_key = merged_item.get("api_key")
        if pipeline_app.is_masked_secret_value(incoming_key):
            item_id = str(merged_item.get("id") or "").strip()
            current_item = current_by_id.get(item_id)
            if current_item is None and index < len(current_items):
                current_item = current_items[index]
            merged_item["api_key"] = (
                str(current_item.get("api_key") or "").strip()
                if isinstance(current_item, dict)
                else ""
            )
        merged_pool.append(merged_item)
    return merged_pool


def merge_preserved_secret_settings(
    payload: dict[str, Any],
    current_settings: pipeline_app.Settings,
) -> dict[str, Any]:
    merged = dict(payload or {})
    current_values = current_settings.to_dict()
    for key in SECRET_SETTING_KEYS:
        if key in POOL_SECRET_SETTING_KEYS:
            if key in merged:
                merged[key] = merge_preserved_pool_secrets(
                    merged.get(key),
                    current_values.get(key),
                )
            continue
        current_value = str(current_values.get(key, ""))
        incoming_value = str(merged.get(key, "")).strip()
        if current_value and incoming_value == pipeline_app.mask_secret(current_value):
            merged[key] = current_value
    return merged
