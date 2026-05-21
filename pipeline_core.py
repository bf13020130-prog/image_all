#!/usr/bin/env python3
from __future__ import annotations

import base64
import concurrent.futures
from contextlib import contextmanager
import ipaddress
import io
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any

try:
    import requests
except ImportError:
    requests = None

APP_NAME = "imag_Replicate2"
APP_TITLE = "imag_Replicate2"
DEFAULT_API_BASE = "https://api.bltcy.ai"
DEFAULT_CHAT_MODEL = "gpt-5.4"
DEFAULT_COLOR_MATCH_MODEL = "gpt-5.5"
DEFAULT_IMAGE_AGENT_MODEL = "gpt-5.5"
DEFAULT_IMAGE_MODEL = "gpt-image-2"
IMAGE_MODEL_GPT_IMAGE_2 = "gpt-image-2"
IMAGE_MODEL_NANO_BANANA_2 = "gemini-3.1-flash-image-preview"
IMAGE_MODEL_NANO_BANANA_PRO = "gemini-3-pro-image-preview"
DEFAULT_IMAGE_MODEL_GPT_IMAGE_2_ID = "gpt-image-2"
SUPPORTED_IMAGE_MODELS = (
    IMAGE_MODEL_GPT_IMAGE_2,
    IMAGE_MODEL_NANO_BANANA_2,
    IMAGE_MODEL_NANO_BANANA_PRO,
)
LEGACY_IMAGE_MODEL_ALIASES = {
    "nano-banana-2": IMAGE_MODEL_NANO_BANANA_2,
    "nano-banana-2-1k": IMAGE_MODEL_NANO_BANANA_2,
    "nano-banana-2-2k": IMAGE_MODEL_NANO_BANANA_2,
    "nano-banana-2-4k": IMAGE_MODEL_NANO_BANANA_2,
    "nano-banana-pro": IMAGE_MODEL_NANO_BANANA_PRO,
    "nano-banana-pro-1k": IMAGE_MODEL_NANO_BANANA_PRO,
    "nano-banana-pro-2k": IMAGE_MODEL_NANO_BANANA_PRO,
    "nano-banana-pro-4k": IMAGE_MODEL_NANO_BANANA_PRO,
}
DEFAULT_REASONING_EFFORT = "xhigh"
DEFAULT_REASONING_WIRE_FORMAT = "reasoning_effort"
LLM_ENDPOINT_CHAT_COMPLETIONS = "chat_completions"
LLM_ENDPOINT_RESPONSES = "responses"
LLM_ENDPOINT_TYPES = (LLM_ENDPOINT_CHAT_COMPLETIONS, LLM_ENDPOINT_RESPONSES)
DEFAULT_CONNECT_TIMEOUT_SECONDS = 30
DEFAULT_CHAT_READ_TIMEOUT_SECONDS = 600
DEFAULT_IMAGE_READ_TIMEOUT_SECONDS = 300
DEFAULT_DOWNLOAD_READ_TIMEOUT_SECONDS = 180
DEFAULT_RETRY_COUNT = 3
DEFAULT_CHAT_MAX_TOKENS = 0
DEFAULT_PROMPT_COUNT = 4
DEFAULT_ASPECT_RATIO = "auto"
DEFAULT_OUTPUT_RESOLUTION = "auto"
DEFAULT_OUTPUT_ASPECT_RATIO = "auto"
DEFAULT_IMAGE_AGENT_GPT_OUTPUT_RESOLUTION = "1k"
DEFAULT_IMAGE_AGENT_NANO_BANANA_OUTPUT_RESOLUTION = "2k"
DEFAULT_IMAGES_PER_PROMPT = 1
DEFAULT_CONCURRENCY = 4
MAX_IMAGE_AGENT_REQUEST_COUNT = 20
MAX_IMAGE_EDIT_INPUT_IMAGES = 16
IMAGE_AGENT_CONTEXT_TOKEN_LIMIT = 900_000
IMAGE_AGENT_CONTEXT_CHAR_LIMIT = 1_800_000
IMAGE_AGENT_CONTEXT_RECENT_FULL_MESSAGES = 12
IMAGE_AGENT_CONTEXT_MAX_MESSAGES = 80
IMAGE_AGENT_CONTEXT_MAX_RESULT_URLS = 8
IMAGE_AGENT_CONTEXT_MAX_ATTACHMENTS = 12
IMAGE_AGENT_CONTEXT_MAX_IMAGE_REFS = 48
IMAGE_AGENT_CONTEXT_MAX_VISUAL_REFS = 10
MAX_STYLE_REFERENCE_IMAGES = 5
MAX_PRODUCT_REFERENCE_IMAGES = 5
MAX_STYLE_REPLICATE2_REFERENCE_IMAGES = 10
STYLE_REPLICATE2_UPLOAD_GATE_REFERENCE_THRESHOLD = 5
STYLE_REPLICATE2_UPLOAD_CONCURRENCY_LIMIT = 5
MIN_MULTIPART_UPLOAD_TIMEOUT_SECONDS = 120
MAX_MULTIPART_UPLOAD_TIMEOUT_SECONDS = 600
MULTIPART_UPLOAD_BYTES_PER_SECOND = 512 * 1024
UPLOAD_WRITE_TIMEOUT_THRESHOLD_BYTES = 1024 * 1024
SETTINGS_AUTOSAVE_DELAY_MS = 300
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504, 524}
RETRYABLE_ERROR_BODY_MARKERS = (
    (
        400,
        (
            "tool choice",
            "image_generation",
            "not found",
            "tools",
        ),
    ),
)
IMAGE_SIZE_MIN_PIXELS = 655_360
IMAGE_SIZE_MAX_PIXELS = 8_294_400
IMAGE_SIZE_MAX_EDGE = 3840
IMAGE_SIZE_MULTIPLE = 16
THUMBNAIL_MAX_EDGE = 360
THUMBNAIL_QUALITY = 78
GPT_IMAGE_SUPPORTED_SIZES = (
    "1024x1024",
    "1536x1024",
    "1024x1536",
    "2048x2048",
    "2048x1152",
    "3840x2160",
    "2160x3840",
)
OUTPUT_RESOLUTION_OPTIONS = ("auto", "1k", "2k", "4k")
OUTPUT_ASPECT_RATIO_OPTIONS = (
    "auto",
    "1:1",
    "1:2",
    "1:4",
    "1:8",
    "2:1",
    "2:3",
    "3:2",
    "3:4",
    "4:1",
    "4:3",
    "4:5",
    "5:4",
    "8:1",
    "9:16",
    "16:9",
    "21:9",
)
NANO_BANANA_COMMON_ASPECT_RATIOS = {
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
}
NANO_BANANA_2_ONLY_ASPECT_RATIOS = {"1:4", "4:1", "1:8", "8:1"}
NANO_BANANA_MODELS = (IMAGE_MODEL_NANO_BANANA_2, IMAGE_MODEL_NANO_BANANA_PRO)
OUTPUT_RESOLUTION_LONG_EDGE = {
    "1k": 1024,
    "2k": 2048,
    "4k": 3840,
}
OUTPUT_RESOLUTION_TARGET_EDGE_MODE = {
    "1k": "short",
    "2k": "long",
    "4k": "long",
}
OUTPUT_RESOLUTION_SIZE_OVERRIDES = {
    "1k": {
        "1:1": "1024x1024",
        "1:2": "1024x2048",
        "2:1": "2048x1024",
        "2:3": "1024x1536",
        "3:2": "1536x1024",
        "3:4": "1008x1344",
        "4:3": "1344x1008",
        "4:5": "1024x1280",
        "5:4": "1280x1024",
        "9:16": "1008x1792",
        "16:9": "1792x1008",
        "21:9": "2352x1008",
    }
}
OUTPUT_RESOLUTION_LABELS = {
    "auto": "auto",
    "1k": "1K",
    "2k": "2K",
    "4k": "4K",
}
OUTPUT_ASPECT_RATIO_LABELS = {
    "auto": "auto（Gemini 生图使用不了）",
    "1:1": "1:1（正方形）",
    "1:2": "1:2（Gemini 生图使用不了）",
    "1:4": "1:4（gemini-3.1-flash专属）",
    "1:8": "1:8（gemini-3.1-flash专属）",
    "2:1": "2:1（Gemini 生图使用不了）",
    "2:3": "2:3（标准照片比例）",
    "3:2": "3:2（标准照片比例）",
    "3:4": "3:4（传统相机比例）",
    "4:1": "4:1（gemini-3.1-flash专属）",
    "4:3": "4:3（传统相机比例）",
    "4:5": "4:5（Instagram比例）",
    "5:4": "5:4（Instagram比例）",
    "8:1": "8:1（gemini-3.1-flash专属）",
    "9:16": "9:16（手机竖屏）",
    "16:9": "16:9（手机横屏）",
    "21:9": "21:9（超宽屏电影比例）",
}
LEGACY_OUTPUT_PRESET_ALIASES = {
    "1:1": "1024x1024",
    "3:2": "1536x1024",
    "2:3": "1024x1536",
    "7:4": "1792x1024",
    "4:7": "1024x1792",
}
LEGACY_OUTPUT_SELECTION_ALIASES = {
    "auto": (DEFAULT_OUTPUT_RESOLUTION, DEFAULT_OUTPUT_ASPECT_RATIO),
    "1024x1024": ("1k", "1:1"),
    "1536x1024": ("2k", "3:2"),
    "1024x1536": ("2k", "2:3"),
    "2048x2048": ("2k", "1:1"),
    "2048x1152": ("2k", "16:9"),
    "2160x3840": ("4k", "9:16"),
    "3840x2160": ("4k", "16:9"),
    "16:9": ("2k", "16:9"),
    "9:16": ("4k", "9:16"),
    "1792x1024": ("2k", "16:9"),
    "1024x1792": ("4k", "9:16"),
}
SUPPORTED_OUTPUT_PRESETS = (
    "auto",
    "1024x1024",
    "1536x1024",
    "1024x1536",
    "2048x2048",
    "2048x1152",
    "2160x3840",
    "3840x2160",
    "16:9",
    "9:16",
)
REMOVED_OUTPUT_PRESET_FALLBACKS = {
    "1792x1024": "2048x1152",
    "1024x1792": "2160x3840",
}
ASPECT_RATIO_SIZE_ALIASES = {
    "16:9": "2048x1152",
    "9:16": "2160x3840",
}
OUTPUT_PRESET_LABELS = {
    "auto": "auto · 默认",
    "1024x1024": "1024x1024 · 正方形",
    "1536x1024": "1536x1024 · 横版",
    "1024x1536": "1024x1536 · 竖版",
    "1792x1024": "1792x1024 · 宽横版",
    "1024x1792": "1024x1792 · 长竖版",
    "2048x2048": "2048x2048 · 2K 正方形",
    "2048x1152": "2048x1152 · 2K 横版",
    "3840x2160": "3840x2160 · 4K 横版",
    "2160x3840": "2160x3840 · 4K 竖版",
    "16:9": "16:9 · 自动横版",
    "9:16": "9:16 · 自动竖版",
}
MAX_IMAGE_CONCURRENCY = 200


class SharedRenderGate:
    def __init__(self, capacity: int) -> None:
        self.capacity = max(1, min(MAX_IMAGE_CONCURRENCY, int(capacity)))
        self._semaphore = threading.BoundedSemaphore(self.capacity)
        self._lock = threading.Lock()
        self._in_use = 0

    def acquire(self) -> None:
        self._semaphore.acquire()
        with self._lock:
            self._in_use += 1

    def release(self) -> None:
        with self._lock:
            if self._in_use > 0:
                self._in_use -= 1
        self._semaphore.release()

    def status(self) -> dict[str, int]:
        with self._lock:
            in_use = self._in_use
        return {
            "capacity": self.capacity,
            "in_use": in_use,
            "available": max(0, self.capacity - in_use),
        }


_shared_render_gate: SharedRenderGate | None = None

LEGACY_SYSTEM_PROMPT = textwrap.dedent(
    """
    You are a commercial beauty still-life prompt generator.

    Your only job is to generate exactly the requested number of highly detailed English image-generation prompts based on:
    1) one style reference image
    2) one product reference image

    You must not output analysis, reasoning, summaries, JSON, section headers, notes, or any Chinese.
    Output only the final prompts, numbered exactly as requested.

    Rules:
    - Learn only transferable style language from the style reference image: lighting quality, color atmosphere, material mood, negative space, editorial tone, softness, luxury feeling, spatial calmness.
    - Do not copy the exact composition, object positions, crop, camera angle, framing, prop placement, or layout from the style reference.
    - Preserve the product identity from the product image with high fidelity: bottle proportion, silhouette, transparent glass body, top rim texture, inward curved contour, black cap/base, front label zone, realistic glass highlights and reflections.
    - Every prompt must create a new advertising scene, not a replaced-copy version of the reference.
    - Keep all prompts premium, restrained, elegant, quiet, editorial, realistic, and suitable for luxury fragrance / beauty / personal care advertising.
    - Avoid cheap e-commerce style, plastic-looking surfaces, distorted bottle shapes, duplicated products, warped caps, unreadable labels, random text, cluttered backgrounds, harsh flash, oversaturation, and low-end CGI.

    Each prompt must naturally include all of the following:
    1. product identity
    2. scene and environment
    3. composition and placement
    4. camera angle and shot distance
    5. lens or focal-length feeling
    6. lighting direction and light quality
    7. color palette and mood
    8. props and materials
    9. reflection / shadow / transparency behavior
    10. focus and depth of field
    11. realism and texture quality
    12. negative constraints

    Make the prompts visually rich and specific.
    Each prompt should be around 100 to 150 English words.
    Each prompt must feel like a distinct commercial setup, not just adjective variation.
    """
).strip()

SYSTEM_PROMPT = textwrap.dedent(
    """
    你是一名商业美妆静物提示词生成器。

    你的唯一工作是根据以下两项内容，生成恰好20条细节丰富的英文图像生成提示词：
    1）一张风格参考图
    2）一张产品参考图

    你不得输出分析、推导、总结、JSON格式、章节标题、注释以及任何中文内容。仅输出编号01至20的20条最终提示词。

    规则：
    - 仅从风格参考图中提取可通用的风格要素：光影质感、色彩氛围、材质调性、留白空间、杂志大片格调、柔和质感、高级奢华感、静谧空间氛围。
    - 不得照搬风格参考图的构图、物品摆放位置、画面裁切、拍摄视角、画面取景、道具排布与整体布局。
    - 高度还原产品参考图中的产品特征：瓶身比例、外形轮廓、通透玻璃瓶身、瓶口纹理、内凹弧形线条、黑色瓶盖与瓶底、正面标签区域、真实玻璃高光与反光效果。
    - 每条提示词都要打造全新广告场景，不得照搬复刻参考图画面。
    - 所有提示词风格高端克制、雅致静谧、杂志大片质感、写实自然，适配高端香水、美妆、个人护理产品广告使用。
    - 杜绝廉价电商画风、塑料质感表面、畸形瓶身、重复同款产品、变形瓶盖、模糊标签、杂乱文字、繁杂背景、刺眼闪光灯、色彩过艳、低端电脑合成效果。

    每条提示词必须完整包含以下全部要素：
    1. 产品特征
    2. 场景环境
    3. 构图与摆放方式
    4. 拍摄角度与拍摄距离
    5. 镜头焦段观感
    6. 光线方向与光影质感
    7. 色彩搭配与整体氛围
    8. 道具与材质
    9. 反光、阴影、通透光影效果
    10. 对焦范围与景深效果
    11. 写实程度与材质细节质感
    12. 负面限制要求

    提示词画面细节饱满、描述具体，单条英文篇幅控制在100–150个单词。
    每条提示词对应一套独立商业拍摄场景，不只是简单替换形容词。
    """
).strip()

PREVIOUS_SYSTEM_PROMPT = SYSTEM_PROMPT

PRE_MULTI_SOURCE_SYSTEM_PROMPT = textwrap.dedent(
    """
    你是一名商业美妆静物提示词生成器。

    你的唯一工作是根据以下两项内容，生成恰好20条细节丰富的英文图像生成提示词：
    1）一张风格参考图
    2）一张产品参考图

    你不得输出分析、推导、总结、JSON格式、章节标题、注释以及任何中文内容。仅输出编号01至20的20条最终提示词。

    规则：
    - 从风格参考图中提取可通用的风格要素：光影质感、色彩氛围、材质调性、留白空间、杂志大片格调、柔和质感、高级奢华感、静谧空间氛围，同时抽取参考图中的关键道具或特色元素并在生成场景中独立组合和排列。
    - 不得照搬风格参考图的构图、物品摆放位置、画面裁切、拍摄视角、道具排布与整体布局。
    - 高度还原产品参考图中的产品特征：瓶身比例、外形轮廓、通透玻璃瓶身、瓶口纹理、内凹弧形线条、黑色瓶盖与瓶底、正面标签区域、真实玻璃高光与反光效果。
    - 每条提示词都要打造全新广告场景，不得照搬复刻参考图画面。
    - 所有提示词风格高端克制、雅致静谧、杂志大片质感、写实自然，适配高端香水、美妆、个人护理产品广告使用。
    - 杜绝廉价电商画风、塑料质感表面、畸形瓶身、重复同款产品、变形瓶盖、模糊标签、杂乱文字、繁杂背景、刺眼闪光灯、色彩过艳、低端电脑合成效果。

    每条提示词必须完整包含以下全部要素：
    1. 产品特征
    2. 场景环境
    3. 构图与摆放方式
    4. 拍摄角度与拍摄距离
    5. 镜头焦段观感
    6. 光线方向与光影质感
    7. 色彩搭配与整体氛围
    8. 道具与材质
    9. 反光、阴影、通透光影效果
    10. 对焦范围与景深效果
    11. 写实程度与材质细节质感
    12. 负面限制要求

    提示词画面细节饱满、描述具体，单条英文篇幅控制在100–150个单词。
    每条提示词对应一套独立商业拍摄场景，不只是简单替换形容词。
    """
).strip()

SYSTEM_PROMPT = textwrap.dedent(
    """
    你是一名商业美妆静物提示词生成器。

    你的唯一工作是根据以下两组内容，生成恰好20条细节丰富的英文图像生成提示词：
    1）一组风格参考图，数量为1至5张
    2）一组产品参考图，数量为1至5张

    你不得输出分析、推导、总结、JSON格式、章节标题、注释以及任何中文内容。仅输出编号01至20的20条最终提示词。

    规则：
    - 从风格参考图组中综合提取可通用的风格要素：光影质感、色彩氛围、材质调性、留白空间、杂志大片格调、柔和质感、高级奢华感、静谧空间氛围，同时抽取参考图中的关键道具或特色元素并在生成场景中独立组合和排列。
    - 多张风格参考图只用于综合提取可迁移的风格语言、道具元素、色彩氛围、光影质感，不得照搬任意一张参考图的构图、物品摆放位置、画面裁切、拍摄视角、道具排布与整体布局。
    - 从产品参考图组中综合识别产品特征：瓶身比例、外形轮廓、通透玻璃瓶身、瓶口纹理、内凹弧形线条、黑色瓶盖与瓶底、正面标签区域、真实玻璃高光与反光效果。
    - 如果产品参考图展示同一产品的不同角度，必须综合还原同一产品，不要生成多个重复产品。
    - 如果产品参考图展示多个不同产品，除非用户明确要求，只把它们作为产品组或系列参考，不要随意增删、混淆产品身份或把不同产品细节错误拼接。
    - 每条提示词都要打造全新广告场景，不得照搬复刻任何参考图画面。
    - 所有提示词风格高端克制、雅致静谧、杂志大片质感、写实自然，适配高端香水、美妆、个人护理产品广告使用。
    - 杜绝廉价电商画风、塑料质感表面、畸形瓶身、重复同款产品、变形瓶盖、模糊标签、杂乱文字、繁杂背景、刺眼闪光灯、色彩过艳、低端电脑合成效果。

    每条提示词必须完整包含以下全部要素：
    1. 产品特征
    2. 场景环境
    3. 构图与摆放方式
    4. 拍摄角度与拍摄距离
    5. 镜头焦段观感
    6. 光线方向与光影质感
    7. 色彩搭配与整体氛围
    8. 道具与材质
    9. 反光、阴影、通透光影效果
    10. 对焦范围与景深效果
    11. 写实程度与材质细节质感
    12. 负面限制要求

    提示词画面细节饱满、描述具体，单条英文篇幅控制在100–150个单词。
    每条提示词对应一套独立商业拍摄场景，不只是简单替换形容词。
    """
).strip()

DEFAULT_USER_PROMPT = textwrap.dedent(
    """
    以第一组上传图片作为风格参考图组，第二组上传图片作为产品参考图组。

    生成详细的英文图像生成提示词。

    要求：
    - 必须优先学习风格参考图组的整体摄影语言，而不是泛化成普通高端产品图。
    - 请从风格参考图中综合提取：摄影类型、构图语法、镜头距离、裁切方式、光线方向、阴影形态、色彩比例、材质系统、道具逻辑、空间氛围、真实感等级和品牌情绪。
    - 输出的每条提示词都必须明显延续该组风格参考图的共同风格指纹。
    - 不得一比一复刻任意参考图，但允许继承同类裁切、留白、光影、道具密度、空间层次、前景遮挡、镜头距离和材质触感。
    - 产品身份、结构、比例、材质、标签区域和关键细节必须以产品参考图为准。
    - 风格参考图只决定画面风格，不决定产品身份。
    - 每条提示词都要创作新的广告场景，但这些场景应该像同一品牌 campaign 中的不同分镜，而不是彼此割裂的不同摄影风格。
    - 避免普通电商主图、白底图、过度棚拍、廉价CG、风格漂移、构图呆板、道具堆砌、产品孤立展示、与风格参考图无关的泛化高级感。

    无需展示分析过程。
    仅输出最终英文提示词即可。
    """
).strip()

STYLE_REPLICATE2_SYSTEM_PROMPT = textwrap.dedent(
    """
    你是一名通用商品小红书生活方式提示词生成器。

    你的唯一工作是根据一组参考图，生成恰好20条细节丰富的英文图像生成提示词。

    输入内容为：
    1）一组参考图，数量为1至5张

    这些参考图同时承担两种作用：
    - 第一，用于综合提取统一的风格指纹
    - 第二，用于识别画面中出现的产品身份、结构、比例、材质、关键视觉特征以及产品与场景/人物/道具的关系

    你不得输出分析、推导、总结、JSON格式、章节标题、注释以及任何中文内容。仅输出编号01至20的20条最终英文提示词。

    【最高优先级规则】
    你必须先识别这组参考图属于哪一种“内容形式”，并将该内容形式作为最高优先级约束保留下来。

    内容形式包括但不限于：
    1. 手持展示图
    2. 桌面摆拍图
    3. 场景陈列图
    4. 使用中演示图
    5. 人物互动图
    6. 上身/穿戴展示图
    7. 开箱/展示图
    8. 局部细节特写图
    9. 合集/种草图
    10. 适合文字封面的内容图
    11. 其他具有明确内容表达形式的生活方式商品图

    如果参考图属于其中某一种或几种相近的内容形式，生成的提示词必须优先保持同类内容形式，不得自动转化为标准电商主图、通用商业静物广告、纯棚拍品牌KV、脱离生活语境的高端摆拍，除非参考图本身就是这种类型。

    【平台气质要求】
    整体结果必须优先贴近“小红书 / 偏生活感”的视觉语境，即：
    - 有生活方式内容感
    - 有真实分享感
    - 有种草感
    - 有日常使用场景感
    - 有轻商业感，但不能变成硬广
    - 更像内容平台上的优质商品内容图，而不是传统广告海报或电商白底图

    【风格指纹提取要求】
    你必须从参考图组中综合提取可迁移的统一风格指纹，而不是只提取抽象形容词。必须在内部识别并延续以下维度：

    1. 内容形式：参考图属于哪一种生活方式内容图形式，主体与人/手/道具/场景之间的关系如何。
    2. 摄影类型：判断更接近生活方式商品图、种草内容图、使用场景图、桌面摆拍图、人物互动图、开箱展示图、局部特写图、合集封面图或其他内容类型。
    3. 构图语法：提取主体是否居中、偏置、贴边、局部裁切、俯拍、平视、低机位、近景、远景、留白比例、前景遮挡、层次关系、画面边缘是否有元素侵入等。
    4. 镜头语言：提取拍摄距离、焦段观感、景深深浅、虚化程度、是否有局部特写、是否更接近手机拍摄感或相机拍摄感。
    5. 光线系统：提取主光方向、软硬程度、自然光或室内光感、阴影形态、高光质感、反射强度、明暗对比和整体曝光倾向。
    6. 色彩系统：提取主色、辅助色、点缀色、冷暖关系、饱和度、色彩克制程度，以及背景与主体之间的颜色关系。
    7. 材质系统：提取可迁移的材质类型，例如木材、石材、布料、玻璃、金属、纸张、塑料、陶瓷、水面、植物、墙面、桌面、床品等，但不得机械照搬具体摆法。
    8. 道具逻辑：提取道具的类别、数量、密度、摆放方式和叙事作用，例如辅助说明、营造生活感、制造层次、作为前景、作为背景、作为使用场景的一部分等。
    9. 空间气质：提取画面是居家、通勤、浴室、厨房、卧室、桌面、窗边、户外、休闲、旅行、办公、餐桌或其他空间氛围。
    10. 真实感等级：判断参考图更接近真实生活拍摄、轻布景生活方式拍摄、商业摄影、强棚拍、CG渲染或超现实合成，并在生成中保持相同等级。
    11. 平台调性：提取参考图更偏分享感、种草感、教程感、记录感、体验感、氛围感还是产品说明感。
    12. 产品编排语法：提取产品数量、主次关系、与人物/手/使用动作/道具的关系、单品或多品的组合方式。

    【产品识别要求】
    你还必须从同一组参考图中识别产品本身的信息，包括但不限于：
    - 产品类型
    - 产品数量与系列关系
    - 外观结构与轮廓特征
    - 主要材质与表面质感
    - 标签、图案、配色、按钮、瓶盖、包装、接口、纹理等关键识别细节
    - 产品与人/手/道具/使用动作之间的关系
    - 如果是同一系列多个产品，必须理解它们的差异与统一性

    不得将其泛化成任意普通同类产品。必须尽量保留其产品身份、结构轮廓、材质特征和关键外观细节。

    【受控发散要求】
    你必须执行“受控发散”，而不是“自由发散”。

    受控发散的含义是：
    - 固定统一的内容形式
    - 固定统一的小红书生活方式语境
    - 固定统一的产品身份
    - 固定统一的风格世界
    - 在不偏离参考图的前提下，围绕构图、机位、景别、裁切、留白、道具组织、背景细节、产品与场景/人物的关系，生成适合批量出图的一组不同分镜

    当参考图数量较少（尤其是1至3张）时，你必须优先采用“同一内容体系内扩写”的策略：
    1. 优先在同场景或同类场景中做变化，例如同场景不同角度、同布景不同裁切、同一生活方式语境下不同景别、不同留白、不同主体落点。
    2. 允许做有限度的邻近场景扩展，但扩展后的画面仍必须明显属于同一视觉世界、同一内容语境，而不是跳到完全无关的新场景系统。
    3. 允许继承参考图中的构图骨架、内容表达方式和镜头语法，但不得进行一比一复刻。
    4. 不得因为要发散而随意更换内容形式、摄影类型、光线逻辑、主色关系、真实感等级、平台调性或产品外观结构。

    【固定核心 + 变化轴】
    所有提示词都必须遵守“固定核心 + 变化轴”的原则。

    固定核心必须保持一致：
    - 内容形式
    - 小红书/生活方式平台语境
    - 产品身份和关键结构
    - 主要光线系统
    - 色彩主关系
    - 真实感等级
    - 空间气质
    - 道具逻辑
    - 平台调性

    变化轴必须主动拉开差异：
    - 主体位于画面中心 / 偏左 / 偏右 / 偏下 / 贴边
    - 大景别 / 中景 / 近景 / 局部裁切
    - 平视 / 俯拍 / 低机位 / 斜切角度
    - 留白偏左 / 偏右 / 偏上 / 偏下
    - 有前景遮挡 / 无遮挡
    - 单产品 / 多产品 / 与人物或手互动 / 与使用动作互动
    - 道具数量、道具进入方式和背景细节变化
    - 同一空间内不同角落 / 相邻生活场景的小幅变化
    - 近距离细节 / 中距离展示 / 稍远距离环境呈现
    - 适合封面文案的画面留白方式变化

    【严格禁止】
    除非参考图本身如此，否则不得自动生成以下方向：
    - 纯电商白底图
    - 标准商业静物英雄图
    - 过度棚拍硬广
    - 纯品牌KV
    - 廉价CG感
    - 与参考图无关的高端抽象摆拍
    - 与参考图无关的大量装饰道具
    - 产品孤立展示且脱离生活语境
    - 风格漂移、内容形式漂移、产品身份漂移

    【每条提示词必须包含的要素】
    每条提示词必须完整包含以下全部要素：
    1. 产品特征
    2. 内容形式与场景类型
    3. 构图与摆放/互动方式
    4. 拍摄角度与拍摄距离
    5. 镜头焦段观感
    6. 光线方向与光影质感
    7. 色彩搭配与整体氛围
    8. 道具与材质
    9. 背景与空间关系
    10. 对焦范围与景深效果
    11. 写实程度与材质细节质感
    12. 负面限制要求

    【CONTENT FORMAT LOCK】
    每条提示词必须首先保持参考图的内容形式一致性。若参考图更接近手持展示、桌面摆拍、使用中演示、人物互动、上身展示、合集种草或其他生活方式内容图，则生成结果必须优先延续该类内容图逻辑，不得自动转为其他完全不同的内容图类型。

    【PLATFORM LOCK】
    每条提示词都必须优先服务于“小红书 / 偏生活感”的内容语境。画面应更像高质量的生活方式商品内容图，而不是传统广告图、电商图或品牌静物大片。

    【PRODUCT LOCK】
    每条提示词必须把参考图中出现的产品作为最终画面主体参考，不得随意更换产品类型、结构、比例、材质、关键细节或系列逻辑。若参考图中出现的是同一系列多个产品，可以根据画面需要选择单品、双品或系列组合，但必须保持系列一致性与结构真实性。

    【DIVERSITY LOCK】
    20条提示词必须看起来像同一内容系列中的不同分镜，而不是同一条提示词的轻微同义改写。任意两条提示词都不能只是更换抽象形容词，必须在构图骨架、机位、景别、裁切、留白关系、背景细节、人物/手/道具关系和画面组织方式上明显不同。

    提示词画面细节饱满、描述具体，单条英文篇幅控制在100–150个单词。
    每条提示词对应一套独立内容分镜，或者同一内容体系下的独立镜头分镜，而不只是简单替换形容词。
    """
).strip()

STYLE_REPLICATE2_DEFAULT_USER_PROMPT = textwrap.dedent(
    """
    以上传的图片作为唯一参考图组。

    请基于这组图片，生成详细的英文图像生成提示词。

    要求：
    - 必须优先识别这组参考图属于哪一种内容形式，并延续这种内容形式，不要自动转成其他无关的内容图类型。
    - 整体结果必须优先贴近“小红书 / 偏生活感”的视觉语境，体现生活方式内容感、真实分享感、种草感和日常场景感，而不是传统广告图或电商图。
    - 必须优先学习这组参考图的整体摄影语言，而不是泛化成普通高端产品图。
    - 请从参考图中综合提取：内容形式、摄影类型、构图语法、镜头距离、裁切方式、光线方向、阴影形态、色彩比例、材质系统、道具逻辑、空间氛围、真实感等级和平台调性。
    - 输出的每条提示词都必须明显延续该组参考图的共同风格指纹。
    - 同时，必须识别参考图中的产品，并在生成的提示词中保持该产品或该产品系列的身份、比例、结构、材质和关键外观细节。
    - 不得一比一复刻任意参考图，但允许继承同类内容表达方式、构图骨架、裁切、留白、光影、道具密度、空间层次、镜头距离和材质触感。
    - 每条提示词都要创作新的内容分镜，或者在同一内容体系中创作新的镜头分镜；这些结果必须像同一组小红书商品内容中的不同画面，而不是彼此割裂的不同摄影风格。

    关于批量发散：
    - 即使参考图只有1至3张，也必须基于这些参考图进行稳定、可控、可批量的发散生成。
    - 发散不是随意发挥，而是围绕同一内容形式、同一平台语境、同一产品身份、同一风格世界做扩写。
    - 优先允许同场景不同角度、同布景不同裁切、同一空间氛围下不同景别、不同主体落点、不同留白关系、不同前后景层次和不同内容分镜。
    - 也允许做有限度的邻近场景扩展，但扩展后的画面仍必须明显属于同一视觉世界和同一内容语境，不得跳出参考图建立的边界。

    关于批量差异：
    - 每条提示词都必须形成新的内容分镜，不只是替换形容词。
    - 必须主动拉开这些维度的差异：主体位置、景别远近、机位高低、裁切方式、留白方向、前景遮挡、人物/手/道具关系、背景细节、产品编排方式和空间层次。
    - 即使整体风格保持统一，也不能让整组提示词反复使用相同的主体落点、相同的镜头高度、相同的裁切方式、相同的留白方向和相同的画面组织方式。

    关于限制要求：
    - 避免普通电商主图、白底图、过度棚拍、硬广感、廉价CG、风格漂移、内容形式漂移、构图呆板、道具堆砌、产品孤立展示以及与参考图无关的泛化高级感。
    - 不得偏离参考图的整体内容形式和风格世界，不得让产品身份走样，不得随意改动产品结构、比例和关键识别细节。

    无需展示分析过程。
    仅输出最终英文提示词即可。
    """
).strip()

USER_PROMPT_TEMPLATE = textwrap.dedent(
    """
    以第一组上传图片作为风格参考图组，第二组上传图片作为产品参考图组。

    以下是当前任务的用户要求：
    {user_prompt}

    补充执行约束：
    - 当前任务必须生成恰好{prompt_count}条最终提示词，输出编号必须是{numbering_range_cn}。
    - 必须综合全部风格参考图，不得只依赖其中一张，也不得照搬任意一张参考图的构图。
    - 必须综合全部产品参考图，明确保持产品身份、比例、结构、材质、标签区域、瓶盖/瓶身/包装细节。
    - {prompt_count}条提示词必须逐条使用不同的主构图逻辑，不能重复或近似重复产品的主体摆放方式。
    - 严禁整组提示词反复使用相同的主体落点、相同的镜头高度、相同的裁切方式、相同的留白方向、相同的台面结构、相同的道具组织方式。
    - 必须主动拉开这些维度的差异：主体位于画面中心/偏左/偏右/偏下/贴边，大景别/中景/近景/局部裁切，平视/俯拍/仰拍/低机位斜切，前景遮挡/无遮挡，镜面反射/湿润台面/半透明介质/石膏展台/矿石陪体/大面积留白。
    - 任意两条提示词都不能只是更换形容词，必须在场景逻辑、构图骨架、镜头机位、留白关系和道具策略上明显不同。
    - 即使风格参考图氛围统一，也不能把产品连续摆在同一位置或使用同一种视角复刻不同场景。
    - 输出时仍然只允许输出{prompt_count}条英文最终提示词，不允许输出分析、说明、注释或中文。
    """
).strip()

STYLE_REPLICATE2_USER_PROMPT_TEMPLATE = "{user_prompt}"

PRODUCT_REFERENCE_RENDER_PROMPT_PREFIX = textwrap.dedent(
    """
    Use all uploaded images in this generation request as product reference images.
    Synthesize them as references for the same product or product series.
    Preserve product identity, proportions, silhouette, material, label area, cap/body/package structure, transparency, reflections, and all key details.
    Do not duplicate, merge incorrectly, or invent conflicting product structures.
    Follow the scene, lighting, composition, and mood described below:
    """
).strip()

STYLE_REPLICATE2_RENDER_PROMPT_PREFIX = textwrap.dedent(
    """
    Use all uploaded images in this generation request as the only reference images.
    Treat them as references for the lifestyle content format, Xiaohongshu-style visual language, and product or product-series identity.
    Preserve product type, proportions, silhouette, material, label/graphic details, packaging relationship, surface finish, texture, reflections, and all key visual details.
    Keep the output in the same everyday lifestyle content world as the references unless the references themselves are studio ads.
    Do not replace the referenced product with a generic product or unrelated category.
    Do not turn the result into an ecommerce white-background image, hard-sell KV, or isolated studio hero shot unless that is the reference format.
    Do not redraw any reference image one-to-one; create a new lifestyle content frame that follows the prompt below:
    """
).strip()

PRE_TOOL_IMAGE_AGENT_PLANNER_PROMPT = (
    "You are an image-generation planning agent. Return only JSON. Infer image_count "
    "from the user's request, choose output_resolution and output_aspect_ratio from "
    "the backend allowed values, keep backend-selected model unchanged, and explain "
    "how uploaded references should be used. image_count must not exceed "
    "{max_image_count}."
)
PRE_TOOL_IMAGE_AGENT_CREATOR_PROMPT = (
    "You are a commercial image creation agent. Return only JSON with design_strategy "
    "and prompts. Generate one executable English image prompt for each planned "
    "deliverable, respecting the backend-selected model/resolution/aspect ratio and "
    "uploaded references."
)

IMAGE_AGENT_PLANNER_PROMPT = textwrap.dedent(
    """
    You are the planner agent in a tool-driven image assistant workflow. The flow is: planner writes an execution plan first. If the user is asking a normal question or only needs a text reply, return that answer and do not generate images. If the user asks to create, edit, revise, regenerate, or produce visual deliverables, the backend will hand off to image_video_creator immediately after the plan.

    Rules:
    - Answer and write the plan in the same language as the user's request.
    - Call the write_plan tool exactly once.
    - Set needs_image=false and image_count=0 for normal conversation, clarification, explanation, status discussion, or advice that does not request new visual output. Put the complete user-facing answer in response_text.
    - Set needs_image=true when the user asks for image creation, image editing, visual regeneration, or concrete visual deliverables.
    - If the user asks to generate/create/make/design an image but uploads no images, still set needs_image=true and plan a text-to-image task with empty input_images.
    - If the user asks to revise an earlier result, compare references, or says the previous effect is wrong, use context_image_refs to identify the relevant prior input and output images, then set needs_image=true when the intent is to produce another visual result.
    - Do not call multiple tools simultaneously.
    - Preserve the backend-selected logical image model exactly; model switching is not allowed.
    - Do not output concrete image model IDs. The backend maps output_resolution to the configured endpoint, API key, and concrete model ID.
    - When needs_image=true, always pay attention to image quantity. If the user specifies a number, preserve that exact number up to {max_image_count}. If no number is specified, use 1 image.
    - Choose output_resolution and output_aspect_ratio only from the backend allowed values. If the user did not explicitly request a resolution, use the backend default shown in the user message.
    - If the user asks for detail pages, posters, KV, social images, banners, ecommerce assets, or campaign frames, split them into concrete deliverables.
    - If input images are present, state how they should be used: product identity, style, composition, color, material, layout, or mood reference.
    - If context_image_refs are present, treat them as an index of prior input/result images. For follow-up wording like "this one", "previous image", "just now", or "the effect is not right", plan against the latest relevant message's input and result refs together unless the user explicitly points elsewhere.
    - After write_plan succeeds with needs_image=true, the backend will hand off to image_video_creator immediately. Do not ask for approval.
    - If tool calling is unavailable, return one JSON object with the same fields as the write_plan tool arguments and no Markdown.
    """
).strip()

IMAGE_AGENT_CREATOR_PROMPT = textwrap.dedent(
    """
    You are image_video_creator. You create images from text prompts and optional reference images. You write professional image prompts that best fulfill the user's request and the planner's execution plan.

    Rules:
    - First write a concise Design Strategy Doc in the same language as the user's request. Keep it practical: visual goal, style and mood, key subject, composition, color/material logic, and execution notes.
    - Then call generate_image_by_selected_model once for each planned image. The number of tool calls must exactly match the plan image_count.
    - Use the backend-selected logical image model; do not request, mention, or switch to another model.
    - Do not output concrete image model IDs. The backend maps output_resolution to the configured endpoint, API key, and concrete model ID.
    - Choose aspect_ratio and output_resolution from the allowed values. If the user did not explicitly request a resolution, use the backend default shown in the user message. Different deliverables may use different values only when the user requested that or the plan requires it.
    - If the user's message contains input images in XML like <input_images><image file_id="reference_image_1" /></input_images>, parse those file_id values. When images are present, pass them in input_images when they are useful.
    - If the message contains <context_image_refs>, treat those as indexed prior input/result images. For follow-up requests such as "this one", "previous image", "just now", or "the effect is not right", use the latest relevant message's input refs and result refs together unless the user names or uploads another reference. Use only relevant file_id values in input_images, do not include every historical ref.
    - For a brand-new request that does not refer to prior images, leave input_images empty unless current uploaded reference_image_* images are actually needed.
    - If there is more than one input image, use the selected image tool with the input_images list; the backend supports multiple references for this workflow.
    - Preserve product identity, structure, proportions, materials, label areas, packaging geometry, and key details from product references.
    - If references mainly express style or scene, inherit photography language, composition grammar, camera distance, cropping, light direction, shadow quality, color proportion, material system, prop logic, spatial mood, realism level, and brand emotion.
    - Each output must serve a different deliverable and feel like a different frame in the same campaign, not a duplicate.
    - Avoid generic ecommerce white-background images, cheap CG, over-staged studio shots, style drift, stiff composition, and generic premium aesthetics unrelated to the references.
    - Every image prompt must be in English and include subject, scene, composition, camera/lens feel, lighting, materials, color, realism, and negative constraints.
    - If tool calling is unavailable, return one JSON object containing design_strategy and prompts. No Markdown.

    Batch rule:
    - If the user needs more than 10 images, prepare them in batches of at most 10. The backend may execute the batch concurrently after the tool calls are collected.

    Error handling:
    - Never ignore tool errors. If a generation tool fails, explain the specific reason and suggest a concrete retry direction.
    """
).strip()

COLOR_ANALYSIS_SYSTEM_PROMPT = textwrap.dedent(
    """
    你现在是一个精准的视觉色彩分析引擎。请仔细分析我上传的图片，根据图片的实际色彩复杂程度，动态提取出构成画面的核心色板。

    提取规则：

    忽略极小面积的杂色、噪点或无意义的光影渐变过渡色。

    只提取视觉占比超过 5% 的主导色，以及虽然面积小但起到关键点缀作用的醒目颜色。

    颜色总数由图片本身决定，不需要凑数。

    请严格按以下结构输出，不要包含任何开场白或解释：

    1. 【核心色板】
    请用 Markdown 表格呈现，表头必须包含：

    颜色名称（自然、通俗的描述，如“鼠尾草绿”、“奶油白”）

    HEX 色值

    RGB 色值

    大致占比（%）

    2. 【整体视觉风格】
    该部分需包含 2 至 3 句简洁、综合性的中文分析，描述上方色彩所体现出的独特氛围、色彩和谐性，分析内容必须贴合所上传图片的具体风格与色彩特征。
    """
).strip()

COLOR_ANALYSIS_IMAGE_PROMPT = textwrap.dedent(
    """
    你现在是一个精准的视觉色彩分析引擎。请仔细分析我上传的图片，根据图片的实际色彩复杂程度，动态提取出构成画面的核心色板。

    创建一张精致、简洁、专业的信息图风格数字图像，用于可视化所上传图片的色彩方案。画面中只能包含详细的色彩信息和视觉风格分析，不能出现原图中的产品、场景或任何原始元素。

    顶部区域：标题
    在顶部使用清晰、优雅的无衬线字体显示标题：
    视觉色彩方案分析

    中部区域：色板网格
    在标题下方，呈现一个结构清晰的色彩图块网格（例如 2 行 4 列，或 3 行 3 列，具体可根据上传图片的色彩丰富程度来决定）。每个色块应为纯色显示的标准矩形或圆角方块。在每个色块下方，用清晰易读的排版列出以下准确的色彩信息（模型需基于图像内容自行综合判断）：

    色号（例如：Color 1、Color 2 等）

    HEX 色值（例如：#XXXXXX）

    RGB 数值（例如：R:XX G:XX B:XX）

    估算占比（例如：XX%）

    底部区域：整体视觉风格分析
    在底部使用干净、清晰的字体创建一个标题为“整体视觉风格分析”的分析区域。该部分需包含 2 至 3 句简洁、综合性的中文分析，描述上方色彩所体现出的独特氛围、色彩和谐性，分析内容必须贴合所上传图片的具体风格与色彩特征。

    美术风格要求
    背景必须为干净、极简的白色或浅灰色。整体视觉应精准、信息化且美观。确保所有数据都经过合理综合，并准确匹配上传图片的整体色调与颜色特征。最终画面中不得出现上传图片中的任何原始元素。
    """
).strip()

COLORIZE_PROMPT = "使用参考图2的颜色对参考图1进行上色"
COLORIZE_WITH_ANALYSIS_PROMPT = "用以上色彩对图片进行上色"


def migrate_system_prompt(value: str) -> str:
    text = str(value or "").strip()
    if not text or text in {
        LEGACY_SYSTEM_PROMPT,
        PREVIOUS_SYSTEM_PROMPT,
        PRE_MULTI_SOURCE_SYSTEM_PROMPT,
    }:
        return SYSTEM_PROMPT
    return text


class AppError(RuntimeError):
    pass


def configure_shared_render_gate(size: int | None) -> None:
    global _shared_render_gate
    if size is None:
        _shared_render_gate = None
        return
    bounded_size = max(1, min(MAX_IMAGE_CONCURRENCY, int(size)))
    if _shared_render_gate is not None:
        if _shared_render_gate.capacity == bounded_size:
            return
        if _shared_render_gate.status()["in_use"] > 0:
            return
    _shared_render_gate = SharedRenderGate(bounded_size)


def shared_render_pool_status() -> dict[str, int]:
    gate = _shared_render_gate
    if gate is None:
        return {"capacity": 0, "in_use": 0, "available": 0}
    return gate.status()


@contextmanager
def shared_render_slot() -> Any:
    gate = _shared_render_gate
    if gate is None:
        yield
        return
    gate.acquire()
    try:
        yield
    finally:
        gate.release()


@dataclass
class Settings:
    use_system_proxy: bool = False
    llm_api_base: str = DEFAULT_API_BASE
    llm_api_key: str = "replace-me"
    chat_model: str = DEFAULT_CHAT_MODEL
    color_match_api_base: str = DEFAULT_API_BASE
    color_match_api_key: str = "replace-me"
    color_match_model: str = DEFAULT_COLOR_MATCH_MODEL
    image_agent_api_base: str = DEFAULT_API_BASE
    image_agent_api_key: str = "replace-me"
    image_agent_model: str = DEFAULT_IMAGE_AGENT_MODEL
    image_agent_endpoint_type: str = LLM_ENDPOINT_RESPONSES
    system_prompt: str = SYSTEM_PROMPT
    default_user_prompt: str = DEFAULT_USER_PROMPT
    style_replicate2_system_prompt: str = STYLE_REPLICATE2_SYSTEM_PROMPT
    style_replicate2_user_prompt: str = STYLE_REPLICATE2_DEFAULT_USER_PROMPT
    image_agent_planner_prompt: str = IMAGE_AGENT_PLANNER_PROMPT
    image_agent_creator_prompt: str = IMAGE_AGENT_CREATOR_PROMPT
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    reasoning_wire_format: str = DEFAULT_REASONING_WIRE_FORMAT
    llm_connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS
    chat_read_timeout_seconds: int = DEFAULT_CHAT_READ_TIMEOUT_SECONDS
    llm_retry_count: int = DEFAULT_RETRY_COUNT
    image_api_base: str = DEFAULT_API_BASE
    image_api_key: str = "replace-me"
    image_1k_api_key: str = ""
    gpt_image_api_base: str = DEFAULT_API_BASE
    gpt_image_api_key: str = "replace-me"
    gpt_image_1k_api_base: str = DEFAULT_API_BASE
    gpt_image_1k_api_key: str = ""
    gemini_image_api_base: str = DEFAULT_API_BASE
    gemini_image_api_key: str = ""
    image_model: str = DEFAULT_IMAGE_MODEL
    image_model_gpt_image_2: str = DEFAULT_IMAGE_MODEL_GPT_IMAGE_2_ID
    image_model_gpt_image_2_1k: str = DEFAULT_IMAGE_MODEL_GPT_IMAGE_2_ID
    image_connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS
    image_read_timeout_seconds: int = DEFAULT_IMAGE_READ_TIMEOUT_SECONDS
    download_read_timeout_seconds: int = DEFAULT_DOWNLOAD_READ_TIMEOUT_SECONDS
    image_retry_count: int = DEFAULT_RETRY_COUNT
    chat_max_tokens: int = DEFAULT_CHAT_MAX_TOKENS
    default_prompt_count: int = DEFAULT_PROMPT_COUNT
    default_aspect_ratio: str = DEFAULT_ASPECT_RATIO
    default_output_resolution: str = DEFAULT_OUTPUT_RESOLUTION
    default_output_aspect_ratio: str = DEFAULT_OUTPUT_ASPECT_RATIO
    default_images_per_prompt: int = DEFAULT_IMAGES_PER_PROMPT
    default_concurrency: int = DEFAULT_CONCURRENCY

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Settings":
        payload = payload or {}
        merged = cls().to_dict()
        allowed_keys = {item.name for item in fields(cls)}
        legacy_api_base = payload.get(
            "api_base",
            payload.get("llm_api_base", merged["llm_api_base"]),
        )
        legacy_api_key = payload.get(
            "api_key",
            payload.get("llm_api_key", merged["llm_api_key"]),
        )
        legacy_connect_timeout = payload.get(
            "connect_timeout_seconds",
            merged["llm_connect_timeout_seconds"],
        )
        legacy_retry_count = payload.get("retry_count", merged["llm_retry_count"])
        legacy_image_api_base = payload.get("image_api_base", legacy_api_base)
        legacy_image_api_key = payload.get("image_api_key", legacy_api_key)
        legacy_image_1k_api_key = payload.get(
            "image_1k_api_key",
            merged["image_1k_api_key"],
        )
        merged.update(
            {
                "llm_api_base": legacy_api_base,
                "llm_api_key": legacy_api_key,
                "color_match_api_base": payload.get(
                    "color_match_api_base",
                    legacy_api_base,
                ),
                "color_match_api_key": payload.get(
                    "color_match_api_key",
                    legacy_api_key,
                ),
                "image_agent_api_base": payload.get(
                    "image_agent_api_base",
                    legacy_api_base,
                ),
                "image_agent_api_key": payload.get(
                    "image_agent_api_key",
                    legacy_api_key,
                ),
                "llm_connect_timeout_seconds": legacy_connect_timeout,
                "llm_retry_count": legacy_retry_count,
                "image_api_base": legacy_image_api_base,
                "image_api_key": legacy_image_api_key,
                "image_1k_api_key": legacy_image_1k_api_key,
                "gpt_image_api_base": legacy_image_api_base,
                "gpt_image_api_key": legacy_image_api_key,
                "gpt_image_1k_api_base": legacy_image_api_base,
                "gpt_image_1k_api_key": legacy_image_1k_api_key,
                "gemini_image_api_base": legacy_image_api_base,
                "gemini_image_api_key": legacy_image_1k_api_key
                or legacy_image_api_key,
                "image_connect_timeout_seconds": legacy_connect_timeout,
                "image_retry_count": legacy_retry_count,
            }
        )
        for key, value in payload.items():
            if key in allowed_keys:
                merged[key] = value
        merged["use_system_proxy"] = parse_bool_setting(
            merged.get("use_system_proxy"),
            default=False,
        )
        default_resolution, default_ratio = parse_output_selection(
            output_resolution=payload.get("default_output_resolution"),
            output_aspect_ratio=payload.get("default_output_aspect_ratio"),
            legacy_output=payload.get("default_aspect_ratio"),
        )
        merged["default_output_resolution"] = default_resolution
        merged["default_output_aspect_ratio"] = default_ratio
        merged["default_aspect_ratio"] = output_selection_to_legacy_value(
            default_resolution,
            default_ratio,
        )
        merged["llm_api_base"] = (
            str(merged["llm_api_base"]).rstrip("/") or DEFAULT_API_BASE
        )
        merged["llm_api_key"] = str(merged["llm_api_key"]).strip()
        merged["color_match_api_base"] = (
            str(merged["color_match_api_base"]).rstrip("/")
            or merged["llm_api_base"]
        )
        merged["image_agent_api_base"] = (
            str(merged["image_agent_api_base"]).rstrip("/")
            or merged["llm_api_base"]
        )
        if not resolve_secret_value(merged["color_match_api_key"]):
            merged["color_match_api_key"] = merged["llm_api_key"]
        else:
            merged["color_match_api_key"] = str(
                merged["color_match_api_key"]
            ).strip()
        if not resolve_secret_value(merged["image_agent_api_key"]):
            merged["image_agent_api_key"] = merged["llm_api_key"]
        else:
            merged["image_agent_api_key"] = str(
                merged["image_agent_api_key"]
            ).strip()
        merged["image_api_base"] = str(merged["image_api_base"]).rstrip("/")
        merged["gpt_image_api_base"] = (
            str(merged["gpt_image_api_base"]).rstrip("/") or DEFAULT_API_BASE
        )
        merged["gpt_image_1k_api_base"] = (
            str(merged["gpt_image_1k_api_base"]).rstrip("/")
            or merged["gpt_image_api_base"]
            or DEFAULT_API_BASE
        )
        merged["gemini_image_api_base"] = (
            str(merged["gemini_image_api_base"]).rstrip("/") or DEFAULT_API_BASE
        )
        merged["image_api_base"] = merged["gpt_image_api_base"]
        merged["image_api_key"] = merged["gpt_image_api_key"]
        merged["image_1k_api_key"] = merged["gpt_image_1k_api_key"]
        merged["system_prompt"] = migrate_system_prompt(merged["system_prompt"])
        merged["default_user_prompt"] = (
            str(merged["default_user_prompt"]).strip() or DEFAULT_USER_PROMPT
        )
        merged["style_replicate2_system_prompt"] = (
            str(merged["style_replicate2_system_prompt"]).strip()
            or STYLE_REPLICATE2_SYSTEM_PROMPT
        )
        merged["style_replicate2_user_prompt"] = (
            str(merged["style_replicate2_user_prompt"]).strip()
            or STYLE_REPLICATE2_DEFAULT_USER_PROMPT
        )
        merged["color_match_model"] = (
            str(merged["color_match_model"]).strip() or DEFAULT_COLOR_MATCH_MODEL
        )
        merged["image_agent_model"] = (
            str(merged["image_agent_model"]).strip() or DEFAULT_IMAGE_AGENT_MODEL
        )
        merged["image_agent_endpoint_type"] = normalize_llm_endpoint_type(
            merged.get("image_agent_endpoint_type")
        )
        planner_prompt = str(merged["image_agent_planner_prompt"]).strip()
        if (
            not planner_prompt
            or planner_prompt == PRE_TOOL_IMAGE_AGENT_PLANNER_PROMPT
            or planner_prompt.startswith(
                "You are an image-generation planning agent. Convert the user's natural-language request"
            )
        ):
            planner_prompt = IMAGE_AGENT_PLANNER_PROMPT
        merged["image_agent_planner_prompt"] = planner_prompt
        creator_prompt = str(merged["image_agent_creator_prompt"]).strip()
        if (
            not creator_prompt
            or creator_prompt == PRE_TOOL_IMAGE_AGENT_CREATOR_PROMPT
            or creator_prompt.startswith("You are a commercial image creation agent.")
        ):
            creator_prompt = IMAGE_AGENT_CREATOR_PROMPT
        merged["image_agent_creator_prompt"] = creator_prompt
        raw_image_model = str(merged["image_model"]).strip()
        try:
            merged["image_model"] = normalize_image_model(raw_image_model)
        except AppError:
            if raw_image_model.lower().startswith("gpt-image"):
                merged["image_model"] = IMAGE_MODEL_GPT_IMAGE_2
                merged["image_model_gpt_image_2"] = raw_image_model
            else:
                raise
        merged["image_model_gpt_image_2"] = (
            str(merged["image_model_gpt_image_2"]).strip()
            or DEFAULT_IMAGE_MODEL_GPT_IMAGE_2_ID
        )
        merged["image_model_gpt_image_2_1k"] = (
            str(merged["image_model_gpt_image_2_1k"]).strip()
            or merged["image_model_gpt_image_2"]
            or DEFAULT_IMAGE_MODEL_GPT_IMAGE_2_ID
        )
        merged["llm_connect_timeout_seconds"] = int(
            merged["llm_connect_timeout_seconds"]
        )
        merged["chat_read_timeout_seconds"] = int(merged["chat_read_timeout_seconds"])
        merged["llm_retry_count"] = int(merged["llm_retry_count"])
        merged["image_connect_timeout_seconds"] = int(
            merged["image_connect_timeout_seconds"]
        )
        merged["image_read_timeout_seconds"] = int(merged["image_read_timeout_seconds"])
        merged["download_read_timeout_seconds"] = int(
            merged["download_read_timeout_seconds"]
        )
        merged["image_retry_count"] = int(merged["image_retry_count"])
        merged["chat_max_tokens"] = int(merged["chat_max_tokens"])
        merged["default_prompt_count"] = int(merged["default_prompt_count"])
        merged["default_images_per_prompt"] = int(
            merged["default_images_per_prompt"]
        )
        merged["default_concurrency"] = int(merged["default_concurrency"])
        return cls(**merged)

    def to_dict(self) -> dict[str, Any]:
        return {
            "use_system_proxy": self.use_system_proxy,
            "llm_api_base": self.llm_api_base,
            "llm_api_key": self.llm_api_key,
            "chat_model": self.chat_model,
            "color_match_api_base": self.color_match_api_base,
            "color_match_api_key": self.color_match_api_key,
            "color_match_model": self.color_match_model,
            "image_agent_api_base": self.image_agent_api_base,
            "image_agent_api_key": self.image_agent_api_key,
            "image_agent_model": self.image_agent_model,
            "image_agent_endpoint_type": self.image_agent_endpoint_type,
            "system_prompt": self.system_prompt,
            "default_user_prompt": self.default_user_prompt,
            "style_replicate2_system_prompt": self.style_replicate2_system_prompt,
            "style_replicate2_user_prompt": self.style_replicate2_user_prompt,
            "image_agent_planner_prompt": self.image_agent_planner_prompt,
            "image_agent_creator_prompt": self.image_agent_creator_prompt,
            "reasoning_effort": self.reasoning_effort,
            "reasoning_wire_format": self.reasoning_wire_format,
            "llm_connect_timeout_seconds": self.llm_connect_timeout_seconds,
            "chat_read_timeout_seconds": self.chat_read_timeout_seconds,
            "llm_retry_count": self.llm_retry_count,
            "image_api_base": self.image_api_base,
            "image_api_key": self.image_api_key,
            "image_1k_api_key": self.image_1k_api_key,
            "gpt_image_api_base": self.gpt_image_api_base,
            "gpt_image_api_key": self.gpt_image_api_key,
            "gpt_image_1k_api_base": self.gpt_image_1k_api_base,
            "gpt_image_1k_api_key": self.gpt_image_1k_api_key,
            "gemini_image_api_base": self.gemini_image_api_base,
            "gemini_image_api_key": self.gemini_image_api_key,
            "image_model": self.image_model,
            "image_model_gpt_image_2": self.image_model_gpt_image_2,
            "image_model_gpt_image_2_1k": self.image_model_gpt_image_2_1k,
            "image_connect_timeout_seconds": self.image_connect_timeout_seconds,
            "image_read_timeout_seconds": self.image_read_timeout_seconds,
            "download_read_timeout_seconds": self.download_read_timeout_seconds,
            "image_retry_count": self.image_retry_count,
            "chat_max_tokens": self.chat_max_tokens,
            "default_prompt_count": self.default_prompt_count,
            "default_aspect_ratio": output_selection_to_legacy_value(
                self.default_output_resolution,
                self.default_output_aspect_ratio,
            ),
            "default_output_resolution": self.default_output_resolution,
            "default_output_aspect_ratio": self.default_output_aspect_ratio,
            "default_images_per_prompt": self.default_images_per_prompt,
            "default_concurrency": self.default_concurrency,
        }

    def to_public_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload["llm_api_key"] = mask_secret(self.llm_api_key)
        payload["color_match_api_key"] = mask_secret(self.color_match_api_key)
        payload["image_agent_api_key"] = mask_secret(self.image_agent_api_key)
        payload["gpt_image_api_key"] = mask_secret(self.gpt_image_api_key)
        payload["gpt_image_1k_api_key"] = mask_secret(self.gpt_image_1k_api_key)
        payload["gemini_image_api_key"] = mask_secret(self.gemini_image_api_key)
        payload["image_api_key"] = mask_secret(self.gpt_image_api_key)
        payload["image_1k_api_key"] = mask_secret(self.gpt_image_1k_api_key)
        return payload


@dataclass
class SourceSpec:
    file_path: str = ""
    url: str = ""
    file_paths: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)


@dataclass
class RunOptions:
    project_name: str
    prompt_count: int
    output_resolution: str
    output_aspect_ratio: str
    user_prompt: str
    images_per_prompt: int
    concurrency: int
    style_source: SourceSpec
    product_source: SourceSpec


@dataclass
class StyleReplicate2Options:
    project_name: str
    prompt_count: int
    output_resolution: str
    output_aspect_ratio: str
    user_prompt: str
    images_per_prompt: int
    concurrency: int
    reference_source: SourceSpec


@dataclass
class ImageEditOptions:
    project_name: str
    prompt: str
    image_model: str
    output_resolution: str
    output_aspect_ratio: str
    images_per_prompt: int
    input_images: list[str]
    conversation_id: str = ""
    conversation_title: str = ""


@dataclass
class ImageAgentOptions:
    project_name: str
    prompt: str
    image_model: str
    output_resolution: str
    output_aspect_ratio: str
    input_images: list[str]
    conversation_id: str = ""
    conversation_title: str = ""
    conversation_context: str = ""


@dataclass
class ColorMatchOptions:
    project_name: str
    output_resolution: str
    output_aspect_ratio: str
    tone_image: str
    scene_image: str


@dataclass
class HttpResponseData:
    body: bytes
    status_code: int
    headers: dict[str, str]


class UploadGateBody(io.BytesIO):
    def __init__(
        self,
        body: bytes,
        *,
        upload_gate: threading.Semaphore,
        logger: "AppLogger",
        label: str,
    ) -> None:
        super().__init__(body)
        self._upload_gate = upload_gate
        self._logger = logger
        self._label = label
        self._length = len(body)
        self._released = False
        self._release_lock = threading.Lock()

    def _release_upload_gate(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._released = True
            self._upload_gate.release()
        self._logger.log(f"{self._label}: 上传阶段完成，释放上传槽")

    def read(self, size: int = -1) -> bytes:
        chunk = super().read(size)
        if size != 0 and (not chunk or self.tell() >= self._length):
            self._release_upload_gate()
        return chunk

    def close(self) -> None:
        self._release_upload_gate()
        super().close()


@dataclass
class AppContext:
    root_dir: Path
    data_dir: Path
    logs_dir: Path
    config_path: Path
    config_example_path: Path
    history_path: Path
    edit_conversations_path: Path
    app_log_path: Path
    _file_lock: Any = field(default_factory=threading.RLock, repr=False, compare=False)

    @classmethod
    def detect(cls) -> "AppContext":
        if getattr(sys, "frozen", False):
            root_dir = Path(sys.executable).resolve().parent
        else:
            root_dir = Path(__file__).resolve().parent
        return cls(
            root_dir=root_dir,
            data_dir=root_dir / "data",
            logs_dir=root_dir / "logs",
            config_path=root_dir / "config.json",
            config_example_path=root_dir / "config.example.json",
            history_path=root_dir / "data" / "history.json",
            edit_conversations_path=root_dir / "data" / "edit_conversations.json",
            app_log_path=root_dir / "logs" / "app.log",
        )

    def ensure_layout(self) -> None:
        ensure_dir(self.data_dir)
        ensure_dir(self.logs_dir)
        if not self.config_path.exists():
            write_json(self.config_path, self.default_settings_payload())
        else:
            self.migrate_settings_file()
        if not self.history_path.exists():
            write_json(self.history_path, {"runs": []})
        if not self.edit_conversations_path.exists():
            write_json(self.edit_conversations_path, {"conversations": []})
        if not self.app_log_path.exists():
            self.app_log_path.write_text("", encoding="utf-8")

    def default_settings_payload(self) -> dict[str, Any]:
        if self.config_example_path.exists():
            template = read_json_file(self.config_example_path, {})
            if isinstance(template, dict):
                return Settings.from_dict(template).to_dict()
        return Settings().to_dict()

    def migrate_settings_file(self) -> Settings:
        raw_payload = read_json_file(self.config_path, {})
        if not isinstance(raw_payload, dict):
            raw_payload = {}
        default_payload = self.default_settings_payload()
        settings = Settings.from_dict(
            merge_seed_settings_payload(
                raw_payload=raw_payload,
                default_payload=default_payload,
            )
        )
        normalized_payload = settings.to_dict()
        obsolete_keys = {"image_quality"}
        needs_write = any(key in raw_payload for key in obsolete_keys) or raw_payload != normalized_payload
        if needs_write:
            with self._file_lock:
                write_json(self.config_path, normalized_payload)
        return settings

    def load_settings(self) -> Settings:
        return self.migrate_settings_file()

    def save_settings(self, settings: Settings) -> None:
        with self._file_lock:
            write_json(self.config_path, settings.to_dict())

    def save_history(self, entries: list[dict[str, Any]]) -> None:
        with self._file_lock:
            write_json(self.history_path, {"runs": entries})

    def load_history(self) -> list[dict[str, Any]]:
        with self._file_lock:
            payload = read_json_file(self.history_path, {"runs": []})
            runs = payload.get("runs")
            if not isinstance(runs, list):
                return []
            normalized = [entry for entry in runs if isinstance(entry, dict)]
            completed = [
                entry
                for entry in normalized
                if not entry.get("status")
                or entry.get("status") in {"completed", "partial"}
            ]
            for entry in normalized:
                if entry in completed:
                    continue
                run_dir = entry.get("run_dir")
                if isinstance(run_dir, str) and run_dir.strip():
                    cleanup_failed_run_dir(self, Path(run_dir))
            if completed != runs:
                self.save_history(completed)
            return completed

    def append_history(self, entry: dict[str, Any]) -> None:
        with self._file_lock:
            history = self.load_history()
            history.insert(0, entry)
            self.save_history(history)

    def load_edit_conversations(self) -> list[dict[str, Any]]:
        payload = read_json_file(self.edit_conversations_path, {"conversations": []})
        conversations = (
            payload
            if isinstance(payload, list)
            else payload.get("conversations")
        )
        if not isinstance(conversations, list):
            return []
        return [item for item in conversations if isinstance(item, dict)]

    def save_edit_conversations(self, conversations: list[dict[str, Any]]) -> None:
        with self._file_lock:
            write_json(self.edit_conversations_path, {"conversations": conversations})


class AppLogger:
    def __init__(
        self,
        app_log_path: Path,
        *,
        ui_callback: Any | None = None,
        run_log_path: Path | None = None,
        lock: threading.Lock | None = None,
    ) -> None:
        self.app_log_path = app_log_path
        self.ui_callback = ui_callback
        self.run_log_path = run_log_path
        self._lock = lock or threading.Lock()

    def with_run_log(self, run_log_path: Path) -> "AppLogger":
        return AppLogger(
            self.app_log_path,
            ui_callback=self.ui_callback,
            run_log_path=run_log_path,
            lock=self._lock,
        )

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        with self._lock:
            append_line(self.app_log_path, line)
            if self.run_log_path is not None:
                append_line(self.run_log_path, line)
        if self.ui_callback is not None:
            self.ui_callback(line)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def append_line(path: Path, line: str) -> None:
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def write_json(path: Path, payload: Any) -> None:
    path = Path(path)
    ensure_parent(path)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def positive_int(value: Any, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise AppError(f"{name} 必须大于 0。")
    return parsed


def nonnegative_int(value: Any, name: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise AppError(f"{name} 不能小于 0。")
    return parsed


def normalize_llm_endpoint_type(value: Any) -> str:
    endpoint_type = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "chat": LLM_ENDPOINT_CHAT_COMPLETIONS,
        "chat_completion": LLM_ENDPOINT_CHAT_COMPLETIONS,
        "chat_completions": LLM_ENDPOINT_CHAT_COMPLETIONS,
        "completions": LLM_ENDPOINT_CHAT_COMPLETIONS,
        "/v1/chat/completions": LLM_ENDPOINT_CHAT_COMPLETIONS,
        "response": LLM_ENDPOINT_RESPONSES,
        "responses": LLM_ENDPOINT_RESPONSES,
        "/v1/responses": LLM_ENDPOINT_RESPONSES,
    }
    if not endpoint_type:
        return LLM_ENDPOINT_CHAT_COMPLETIONS
    normalized = aliases.get(endpoint_type, endpoint_type)
    if normalized not in LLM_ENDPOINT_TYPES:
        return LLM_ENDPOINT_CHAT_COMPLETIONS
    return normalized


def sanitize_project_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "-", name.strip())
    cleaned = re.sub(r"\s+", "-", cleaned).strip(".- ")
    return cleaned or "untitled-project"


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}***{value[-4:]}"


def resolve_secret_value(value: Any) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or cleaned == "replace-me":
        return ""
    return cleaned


def parse_bool_setting(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


SEED_BACKFILL_KEYS = (
    "use_system_proxy",
    "llm_api_base",
    "llm_api_key",
    "chat_model",
    "color_match_api_base",
    "color_match_api_key",
    "color_match_model",
    "image_agent_api_base",
    "image_agent_api_key",
    "image_agent_model",
    "image_agent_endpoint_type",
    "gpt_image_1k_api_base",
    "gpt_image_1k_api_key",
    "image_model_gpt_image_2_1k",
    "gpt_image_api_base",
    "gpt_image_api_key",
    "image_model_gpt_image_2",
    "gemini_image_api_base",
    "gemini_image_api_key",
    "image_model",
)


SEED_REPLACE_DEFAULT_VALUES = {
    "llm_api_base": DEFAULT_API_BASE,
    "chat_model": DEFAULT_CHAT_MODEL,
    "color_match_api_base": DEFAULT_API_BASE,
    "color_match_model": DEFAULT_COLOR_MATCH_MODEL,
    "image_agent_api_base": DEFAULT_API_BASE,
    "image_agent_model": DEFAULT_IMAGE_AGENT_MODEL,
    "gpt_image_1k_api_base": DEFAULT_API_BASE,
    "image_model_gpt_image_2_1k": DEFAULT_IMAGE_MODEL_GPT_IMAGE_2_ID,
    "gpt_image_api_base": DEFAULT_API_BASE,
    "image_model_gpt_image_2": DEFAULT_IMAGE_MODEL_GPT_IMAGE_2_ID,
    "gemini_image_api_base": DEFAULT_API_BASE,
    "image_model": DEFAULT_IMAGE_MODEL,
}


def seed_value_should_backfill(key: str, current_value: Any, seed_value: Any) -> bool:
    seed_text = str(seed_value or "").strip()
    if not seed_text:
        return False
    if "key" in key.lower():
        return bool(resolve_secret_value(seed_value)) and not bool(
            resolve_secret_value(current_value)
        )
    current_text = str(current_value or "").strip()
    if not current_text:
        return True
    default_value = SEED_REPLACE_DEFAULT_VALUES.get(key)
    if default_value is None:
        return False
    return current_text == str(default_value).strip() and current_text != seed_text


def merge_seed_settings_payload(
    *,
    raw_payload: dict[str, Any],
    default_payload: dict[str, Any],
) -> dict[str, Any]:
    merged = {**default_payload, **raw_payload}
    for key in SEED_BACKFILL_KEYS:
        if key not in default_payload:
            continue
        if seed_value_should_backfill(key, merged.get(key), default_payload.get(key)):
            merged[key] = default_payload[key]
    return merged


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    redacted = dict(headers)
    auth_value = redacted.get("Authorization")
    if auth_value and auth_value.startswith("Bearer "):
        redacted["Authorization"] = f"Bearer {mask_secret(auth_value[7:])}"
    return redacted


def guess_mime_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def encode_image_as_data_url(path: Path) -> str:
    mime_type = guess_mime_type(path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def retry_sleep_seconds(attempt_number: int) -> int:
    return min(15, attempt_number * 3)


def is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUS_CODES


def is_retryable_error_body(status_code: int, body_text: str) -> bool:
    lowered = str(body_text or "").lower()
    return any(
        status_code == marker_status
        and all(marker in lowered for marker in markers)
        for marker_status, markers in RETRYABLE_ERROR_BODY_MARKERS
    )


def format_http_error(label: str, url: str, status_code: int, body_text: str) -> str:
    details = body_text.strip()
    if details:
        return f"{label} failed with HTTP {status_code} from {url}:\n{details}"
    return f"{label} failed with HTTP {status_code} from {url}."


METADATA_IP_BLOCKLIST = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
}
METADATA_HOST_BLOCKLIST = {
    "metadata.google.internal",
}


def private_url_downloads_allowed() -> bool:
    raw_value = os.environ.get(
        "PLATFORM_ALLOW_PRIVATE_URLS",
        os.environ.get("IMAG_ALLOW_PRIVATE_URLS", "1"),
    )
    return str(raw_value).strip().lower() not in {"0", "false", "no", "off"}


def _normalized_url_host(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise AppError("图片链接只支持 http/https。")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise AppError("图片链接缺少主机名。")
    return host


def _ip_is_private_download_target(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolved_host_ips(host: str) -> list[ipaddress._BaseAddress]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    addresses: list[ipaddress._BaseAddress] = []
    try:
        for result in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM):
            address = result[4][0]
            try:
                addresses.append(ipaddress.ip_address(address))
            except ValueError:
                continue
    except socket.gaierror:
        return []
    return addresses


def validate_download_url(url: str) -> None:
    host = _normalized_url_host(url)
    if host in METADATA_HOST_BLOCKLIST:
        raise AppError("图片链接指向云服务器元数据地址，已拦截。")
    if host in {"localhost", "localhost.localdomain"} and not private_url_downloads_allowed():
        raise AppError("服务器部署模式下不允许下载本机/内网图片链接。")

    addresses = _resolved_host_ips(host)
    if any(address in METADATA_IP_BLOCKLIST for address in addresses):
        raise AppError("图片链接指向云服务器元数据地址，已拦截。")
    if not private_url_downloads_allowed() and any(
        _ip_is_private_download_target(address) for address in addresses
    ):
        raise AppError("服务器部署模式下不允许下载本机/内网图片链接。")


def request_bytes_with_retries(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: bytes | None,
    connect_timeout_seconds: int,
    read_timeout_seconds: int,
    retry_count: int,
    label: str,
    logger: AppLogger,
    upload_gate: threading.Semaphore | None = None,
    use_system_proxy: bool = False,
) -> HttpResponseData:
    max_attempts = retry_count + 1
    last_error_message = f"{label} failed without a detailed error."

    for attempt in range(1, max_attempts + 1):
        logger.log(f"{label}: {method} {url} attempt {attempt}/{max_attempts}")
        try:
            effective_read_timeout = None if read_timeout_seconds == 0 else read_timeout_seconds
            if requests is not None:
                request_headers = dict(headers)
                request_body: bytes | UploadGateBody | None = body
                gated_body: UploadGateBody | None = None
                if upload_gate is not None and body:
                    logger.log(f"{label}: 等待上传槽")
                    upload_gate.acquire()
                    logger.log(f"{label}: 已取得上传槽")
                    gated_body = UploadGateBody(
                        body,
                        upload_gate=upload_gate,
                        logger=logger,
                        label=label,
                    )
                    request_body = gated_body
                    request_headers["Content-Length"] = str(len(body))
                try:
                    with requests.Session() as session:
                        session.trust_env = use_system_proxy
                        response = session.request(
                            method,
                            url,
                            headers=request_headers,
                            data=request_body,
                            timeout=(connect_timeout_seconds, effective_read_timeout),
                        )
                finally:
                    if gated_body is not None:
                        gated_body.close()
                if response.status_code >= 400:
                    last_error_message = format_http_error(
                        label,
                        url,
                        response.status_code,
                        response.text,
                    )
                    if attempt < max_attempts and (
                        is_retryable_status(response.status_code)
                        or is_retryable_error_body(response.status_code, response.text)
                    ):
                        wait_seconds = retry_sleep_seconds(attempt)
                        logger.log(
                            f"{label}: HTTP {response.status_code}，{wait_seconds}s 后重试。"
                        )
                        time.sleep(wait_seconds)
                        continue
                    raise AppError(last_error_message)
                logger.log(f"{label}: HTTP {response.status_code} success")
                return HttpResponseData(
                    body=response.content,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                )

            acquired_upload_gate = False
            if upload_gate is not None and body:
                logger.log(f"{label}: 等待上传槽")
                upload_gate.acquire()
                acquired_upload_gate = True
                logger.log(f"{label}: 已取得上传槽")
            try:
                request = urllib.request.Request(url, data=body, headers=headers, method=method)
                opener = (
                    urllib.request.build_opener()
                    if use_system_proxy
                    else urllib.request.build_opener(urllib.request.ProxyHandler({}))
                )
                with opener.open(request, timeout=effective_read_timeout) as response:
                    response_body = response.read()
                    status_code = getattr(response, "status", 200)
                    logger.log(f"{label}: HTTP {status_code} success")
                    return HttpResponseData(
                        body=response_body,
                        status_code=status_code,
                        headers=dict(response.headers.items()),
                    )
            finally:
                if acquired_upload_gate:
                    upload_gate.release()
                    logger.log(f"{label}: 上传请求结束，释放上传槽")
        except urllib.error.HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="replace")
            last_error_message = format_http_error(label, url, exc.code, response_text)
            if attempt < max_attempts and (
                is_retryable_status(exc.code)
                or is_retryable_error_body(exc.code, response_text)
            ):
                wait_seconds = retry_sleep_seconds(attempt)
                logger.log(f"{label}: HTTP {exc.code}，{wait_seconds}s 后重试。")
                time.sleep(wait_seconds)
                continue
            raise AppError(last_error_message) from exc
        except AppError:
            raise
        except Exception as exc:
            last_error_message = f"{label} failed on attempt {attempt}/{max_attempts}: {exc}"
            if attempt < max_attempts:
                wait_seconds = retry_sleep_seconds(attempt)
                logger.log(f"{last_error_message}，{wait_seconds}s 后重试。")
                time.sleep(wait_seconds)
                continue
            raise AppError(last_error_message) from exc

    raise AppError(last_error_message)


def request_json(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    idempotency_key: str | None,
    connect_timeout_seconds: int,
    read_timeout_seconds: int,
    retry_count: int,
    logger: AppLogger,
    label: str,
    request_log_path: Path,
    response_log_path: Path,
    log_payload: Any | None = None,
    upload_gate: threading.Semaphore | None = None,
    use_system_proxy: bool = False,
) -> Any:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    write_json(
        request_log_path,
        {
            "method": "POST",
            "url": url,
            "headers": redact_headers(headers),
            "idempotency_key": idempotency_key,
            "use_system_proxy": use_system_proxy,
            "payload": payload if log_payload is None else log_payload,
        },
    )
    logger.log(f"{label}: 已保存请求日志 {request_log_path}")
    body = json.dumps(payload).encode("utf-8")
    effective_connect_timeout = upload_write_timeout_seconds(
        len(body),
        configured_connect_timeout=connect_timeout_seconds,
    )
    if effective_connect_timeout != connect_timeout_seconds:
        logger.log(
            f"{label}: 请求体约 {len(body) / (1024 * 1024):.1f} MB，写入超时 {effective_connect_timeout}s"
        )
    response = request_bytes_with_retries(
        "POST",
        url,
        headers=headers,
        body=body,
        connect_timeout_seconds=effective_connect_timeout,
        read_timeout_seconds=read_timeout_seconds,
        retry_count=retry_count,
        label=label,
        logger=logger,
        upload_gate=upload_gate,
        use_system_proxy=use_system_proxy,
    )
    try:
        response_json = json.loads(response.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise AppError(f"{label} 返回的 JSON 无法解析。") from exc
    write_json(response_log_path, response_json)
    logger.log(f"{label}: 已保存返回日志 {response_log_path}")
    return response_json


def encode_multipart_form(
    fields: dict[str, Any],
    files: list[tuple[str, Path]],
) -> tuple[bytes, str]:
    boundary = f"----imag-replicate2-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for key, path in files:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{key}"; filename="{path.name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {guess_mime_type(path)}\r\n\r\n".encode("utf-8"),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload_write_timeout_seconds(
    total_bytes: int,
    *,
    configured_connect_timeout: int,
) -> int:
    if total_bytes < UPLOAD_WRITE_TIMEOUT_THRESHOLD_BYTES:
        return configured_connect_timeout
    estimated_seconds = math.ceil(max(0, total_bytes) / MULTIPART_UPLOAD_BYTES_PER_SECOND)
    return max(
        configured_connect_timeout,
        min(
            MAX_MULTIPART_UPLOAD_TIMEOUT_SECONDS,
            max(MIN_MULTIPART_UPLOAD_TIMEOUT_SECONDS, estimated_seconds),
        ),
    )


def multipart_upload_timeout_seconds(
    file_parts: list[tuple[str, Path]],
    *,
    configured_connect_timeout: int,
) -> int:
    total_bytes = 0
    for _, path in file_parts:
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
    return upload_write_timeout_seconds(
        total_bytes,
        configured_connect_timeout=configured_connect_timeout,
    )


def request_multipart_json(
    url: str,
    fields: dict[str, Any],
    *,
    file_parts: list[tuple[str, Path]],
    api_key: str,
    idempotency_key: str | None,
    connect_timeout_seconds: int,
    read_timeout_seconds: int,
    retry_count: int,
    logger: AppLogger,
    label: str,
    request_log_path: Path,
    response_log_path: Path,
    upload_gate: threading.Semaphore | None = None,
    use_system_proxy: bool = False,
) -> Any:
    body, content_type = encode_multipart_form(fields, file_parts)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": content_type,
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    write_json(
        request_log_path,
        {
            "method": "POST",
            "url": url,
            "headers": redact_headers(headers),
            "idempotency_key": idempotency_key,
            "use_system_proxy": use_system_proxy,
            "fields": fields,
            "files": [
                {
                    "field": key,
                    "path": str(path),
                    "name": path.name,
                    "size": path.stat().st_size,
                    "mime_type": guess_mime_type(path),
                }
                for key, path in file_parts
            ],
        },
    )
    logger.log(f"{label}: 已保存请求日志 {request_log_path}")
    effective_connect_timeout = multipart_upload_timeout_seconds(
        file_parts,
        configured_connect_timeout=connect_timeout_seconds,
    )
    if effective_connect_timeout != connect_timeout_seconds:
        total_upload_mb = sum(
            path.stat().st_size for _, path in file_parts if path.exists()
        ) / (1024 * 1024)
        logger.log(
            f"{label}: multipart 上传 {len(file_parts)} 张图，约 {total_upload_mb:.1f} MB，写入超时 {effective_connect_timeout}s"
        )
    response = request_bytes_with_retries(
        "POST",
        url,
        headers=headers,
        body=body,
        connect_timeout_seconds=effective_connect_timeout,
        read_timeout_seconds=read_timeout_seconds,
        retry_count=retry_count,
        label=label,
        logger=logger,
        upload_gate=upload_gate,
        use_system_proxy=use_system_proxy,
    )
    try:
        response_json = json.loads(response.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise AppError(f"{label} 返回的 JSON 无法解析。") from exc
    write_json(response_log_path, response_json)
    logger.log(f"{label}: 已保存返回日志 {response_log_path}")
    return response_json


def numbering_range(prompt_count: int) -> str:
    width = max(2, len(str(prompt_count)))
    return f"{1:0{width}d} to {prompt_count:0{width}d}"


def numbering_range_cn(prompt_count: int) -> str:
    width = max(2, len(str(prompt_count)))
    return f"{1:0{width}d}至{prompt_count:0{width}d}"


def apply_prompt_count_overrides(template_text: str, prompt_count: int) -> str:
    result = str(template_text or "").strip()
    if not result:
        return result

    range_en = numbering_range(prompt_count)
    range_cn = numbering_range_cn(prompt_count)
    for token, replacement in (
        ("{prompt_count}", str(prompt_count)),
        ("{numbering_range}", range_en),
        ("{numbering_range_cn}", range_cn),
    ):
        result = result.replace(token, replacement)

    substitutions = (
        (r"仅输出编号\s*\d{2,3}\s*(?:至|-|to)\s*\d{2,3}", f"仅输出编号{range_cn}"),
        (r"输出编号\s*\d{2,3}\s*(?:至|-|to)\s*\d{2,3}", f"输出编号{range_cn}"),
        (r"编号\s*\d{2,3}\s*(?:至|-|to)\s*\d{2,3}", f"编号{range_cn}"),
        (r"(?<!\d)\d+\s*条", f"{prompt_count}条"),
        (r"(?<!\d)\d+\s*套", f"{prompt_count}套"),
        (r"(?i)\bexactly\s+\d+\b", f"exactly {prompt_count}"),
        (
            r"(?i)\bnumbered\s+\d{2,3}\s*(?:to|-)\s*\d{2,3}\b",
            f"numbered {range_en}",
        ),
    )
    for pattern, replacement in substitutions:
        result = re.sub(pattern, replacement, result)
    return result


def generate_project_name() -> str:
    return "image"


def render_user_prompt(
    *,
    prompt_count: int,
    user_prompt: str,
) -> str:
    resolved_user_prompt = apply_prompt_count_overrides(
        user_prompt.strip() or DEFAULT_USER_PROMPT,
        prompt_count,
    )
    try:
        return USER_PROMPT_TEMPLATE.format(
            prompt_count=prompt_count,
            numbering_range=numbering_range(prompt_count),
            numbering_range_cn=numbering_range_cn(prompt_count),
            user_prompt=resolved_user_prompt,
        )
    except KeyError as exc:
        placeholder = exc.args[0]
        raise AppError(
            f"用户提示词模板包含未知占位符：{placeholder}。可用占位符：{{user_prompt}}、{{prompt_count}}、{{numbering_range}}、{{numbering_range_cn}}。"
        ) from exc


def render_system_prompt(system_prompt: str, prompt_count: int) -> str:
    return apply_prompt_count_overrides(
        system_prompt.strip() or SYSTEM_PROMPT,
        prompt_count,
    )


def render_style_replicate2_user_prompt(
    *,
    prompt_count: int,
    user_prompt: str,
) -> str:
    resolved_user_prompt = apply_prompt_count_overrides(
        user_prompt.strip() or STYLE_REPLICATE2_DEFAULT_USER_PROMPT,
        prompt_count,
    )
    try:
        return STYLE_REPLICATE2_USER_PROMPT_TEMPLATE.format(
            prompt_count=prompt_count,
            numbering_range=numbering_range(prompt_count),
            numbering_range_cn=numbering_range_cn(prompt_count),
            user_prompt=resolved_user_prompt,
        )
    except KeyError as exc:
        placeholder = exc.args[0]
        raise AppError(
            f"复刻风格图片2用户提示词模板包含未知占位符：{placeholder}。可用占位符：{{user_prompt}}、{{prompt_count}}、{{numbering_range}}、{{numbering_range_cn}}。"
        ) from exc


def render_style_replicate2_system_prompt(
    settings: Settings,
    prompt_count: int,
) -> str:
    return apply_prompt_count_overrides(
        settings.style_replicate2_system_prompt.strip()
        or STYLE_REPLICATE2_SYSTEM_PROMPT,
        prompt_count,
    )


def chat_payload(
    settings: Settings,
    *,
    style_images: list[Path],
    product_images: list[Path],
    prompt_count: int,
    user_prompt: str,
) -> dict[str, Any]:
    max_tokens = settings.chat_max_tokens or max(1200, prompt_count * 320)
    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": render_user_prompt(
                prompt_count=prompt_count,
                user_prompt=user_prompt,
            ),
        },
        {
            "type": "text",
            "text": (
                f"风格参考图组：共 {len(style_images)} 张。"
                "以下图片只用于综合提取风格语言、光影、色彩、材质、道具元素和氛围，不能照搬构图。"
            ),
        },
    ]
    for index, image_path in enumerate(style_images, start=1):
        user_content.extend(
            [
                {"type": "text", "text": f"风格参考图 {index}"},
                {
                    "type": "image_url",
                    "image_url": {"url": encode_image_as_data_url(image_path)},
                },
            ]
        )
    user_content.append(
        {
            "type": "text",
            "text": (
                f"产品参考图组：共 {len(product_images)} 张。"
                "以下图片用于综合识别产品身份、结构、比例、材质、标签区域和关键细节。"
            ),
        }
    )
    for index, image_path in enumerate(product_images, start=1):
        user_content.extend(
            [
                {"type": "text", "text": f"产品参考图 {index}"},
                {
                    "type": "image_url",
                    "image_url": {"url": encode_image_as_data_url(image_path)},
                },
            ]
        )
    payload: dict[str, Any] = {
        "model": settings.chat_model,
        "stream": False,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "system",
                "content": render_system_prompt(settings.system_prompt, prompt_count),
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
    }
    if settings.reasoning_wire_format == "reasoning_effort":
        payload["reasoning_effort"] = settings.reasoning_effort
    else:
        payload["reasoning"] = {"effort": settings.reasoning_effort}
    return payload


def style_replicate2_chat_payload(
    settings: Settings,
    *,
    reference_images: list[Path],
    prompt_count: int,
    user_prompt: str,
) -> dict[str, Any]:
    max_tokens = settings.chat_max_tokens or max(1200, prompt_count * 320)
    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": render_style_replicate2_user_prompt(
                prompt_count=prompt_count,
                user_prompt=user_prompt,
            ),
        },
        {
            "type": "text",
            "text": (
                f"上传参考图组：共 {len(reference_images)} 张。"
                "以下图片是唯一参考，必须同时用于识别内容形式、小红书生活方式语境、统一风格指纹和产品/产品系列身份，不能照搬构图。"
            ),
        },
    ]
    for index, image_path in enumerate(reference_images, start=1):
        user_content.extend(
            [
                {"type": "text", "text": f"上传参考图 {index}"},
                {
                    "type": "image_url",
                    "image_url": {"url": encode_image_as_data_url(image_path)},
                },
            ]
        )
    payload: dict[str, Any] = {
        "model": settings.chat_model,
        "stream": False,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "system",
                "content": render_style_replicate2_system_prompt(
                    settings,
                    prompt_count,
                ),
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
    }
    if settings.reasoning_wire_format == "reasoning_effort":
        payload["reasoning_effort"] = settings.reasoning_effort
    else:
        payload["reasoning"] = {"effort": settings.reasoning_effort}
    return payload


def color_analysis_chat_payload(settings: Settings, *, tone_image: Path) -> dict[str, Any]:
    max_tokens = settings.chat_max_tokens or 1800
    payload: dict[str, Any] = {
        "model": settings.color_match_model or DEFAULT_COLOR_MATCH_MODEL,
        "stream": False,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "system",
                "content": COLOR_ANALYSIS_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "分析"},
                    {
                        "type": "image_url",
                        "image_url": {"url": encode_image_as_data_url(tone_image)},
                    },
                ],
            },
        ],
    }
    if settings.reasoning_wire_format == "reasoning_effort":
        payload["reasoning_effort"] = settings.reasoning_effort
    else:
        payload["reasoning"] = {"effort": settings.reasoning_effort}
    return payload


def render_image_agent_system_prompt(prompt_template: str, fallback: str) -> str:
    template = prompt_template.strip() or fallback
    rendered = template.replace("{max_image_count}", str(MAX_IMAGE_AGENT_REQUEST_COUNT))
    return rendered.replace("{{", "{").replace("}}", "}")


def image_agent_allowed_aspect_ratios(image_model: str) -> list[str]:
    model = normalize_image_model(image_model)
    if model == IMAGE_MODEL_NANO_BANANA_PRO:
        return [item for item in OUTPUT_ASPECT_RATIO_OPTIONS if item in NANO_BANANA_COMMON_ASPECT_RATIOS]
    if model == IMAGE_MODEL_NANO_BANANA_2:
        return [
            item
            for item in OUTPUT_ASPECT_RATIO_OPTIONS
            if item in NANO_BANANA_COMMON_ASPECT_RATIOS
            or item in NANO_BANANA_2_ONLY_ASPECT_RATIOS
        ]
    return list(OUTPUT_ASPECT_RATIO_OPTIONS)


def image_agent_allowed_resolutions(image_model: str) -> list[str]:
    return [item for item in OUTPUT_RESOLUTION_OPTIONS if item != "auto"]


def image_agent_allowed_resolutions_for_settings(
    settings: Settings,
    image_model: str,
) -> list[str]:
    model = normalize_image_model(image_model)
    if is_nano_banana_model(model):
        if resolve_secret_value(settings.gemini_image_api_key):
            return image_agent_allowed_resolutions(model)
        return []
    allowed: list[str] = []
    if resolve_secret_value(settings.gpt_image_1k_api_key) or resolve_secret_value(
        settings.image_1k_api_key
    ):
        allowed.append("1k")
    if resolve_secret_value(settings.gpt_image_api_key) or resolve_secret_value(
        settings.image_api_key
    ):
        allowed.extend(["2k", "4k"])
    return allowed


def image_agent_default_output_resolution(image_model: str) -> str:
    if is_nano_banana_model(image_model):
        return DEFAULT_IMAGE_AGENT_NANO_BANANA_OUTPUT_RESOLUTION
    return DEFAULT_IMAGE_AGENT_GPT_OUTPUT_RESOLUTION


EXPLICIT_OUTPUT_RESOLUTION_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:1\s*k|2\s*k|4\s*k|一\s*k|二\s*k|两\s*k|四\s*k)(?![a-z0-9])|(?<!\d)\d{3,4}\s*[x×]\s*\d{3,4}(?!\d)",
    re.IGNORECASE,
)


def user_prompt_mentions_output_resolution(text: str) -> bool:
    return bool(EXPLICIT_OUTPUT_RESOLUTION_PATTERN.search(str(text or "")))


def image_agent_resolutions_for_prompt(
    *,
    user_prompt: str,
    image_model: str,
    available_resolutions: list[str],
) -> list[str]:
    if user_prompt_mentions_output_resolution(user_prompt):
        return list(available_resolutions)
    default_resolution = image_agent_default_output_resolution(image_model)
    if default_resolution in available_resolutions:
        return [default_resolution]
    return []


def image_agent_effective_model_hint(
    settings: Settings,
    *,
    image_model: str,
    output_resolution: str,
    output_aspect_ratio: str,
) -> str:
    model = normalize_image_model(image_model)
    resolution = str(output_resolution or "").strip().lower()
    if resolution != "agent":
        return resolve_effective_image_model(
            settings=settings,
            image_model=model,
            output_resolution=normalize_output_resolution(resolution),
            output_aspect_ratio=output_aspect_ratio,
        )
    if is_nano_banana_model(model):
        return (
            "由后端按 Agent 选择的分辨率映射；Gemini/banana 使用当前逻辑模型作为实际请求模型"
        )
    model_1k = resolve_effective_image_model(
        settings=settings,
        image_model=model,
        output_resolution="1k",
        output_aspect_ratio="1:1",
    )
    model_2k4k = resolve_effective_image_model(
        settings=settings,
        image_model=model,
        output_resolution="2k",
        output_aspect_ratio="1:1",
    )
    return (
        "由后端按 Agent 选择的分辨率映射；"
        f"1K -> {model_1k}，2K/4K -> {model_2k4k}"
    )


def image_agent_allowed_output_text(
    image_model: str,
    *,
    allowed_resolutions: list[str] | None = None,
    default_resolution: str | None = None,
) -> str:
    resolutions = ", ".join(
        allowed_resolutions or image_agent_allowed_resolutions(image_model)
    )
    ratios = ", ".join(image_agent_allowed_aspect_ratios(image_model))
    lines = [
        f"allowed_output_resolutions=[{resolutions}]",
        f"allowed_output_aspect_ratios=[{ratios}]",
    ]
    if default_resolution:
        lines.append(f"default_output_resolution_if_user_unspecified={default_resolution}")
    return "\n".join(lines)


def estimated_context_tokens(text: str) -> int:
    # Mixed Chinese/English heuristic. It intentionally underuses the 1M window.
    return max(1, math.ceil(len(text or "") / 2))


def truncate_text(value: Any, max_chars: int) -> str:
    text = str(value or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 18)].rstrip() + "...<truncated>"


def compact_url(value: Any, max_chars: int = 240) -> str:
    return truncate_text(str(value or "").strip(), max_chars)


def xml_attr(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def parse_agent_conversation_context_payload(raw_value: str) -> dict[str, Any]:
    text = str(raw_value or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def find_saved_conversation(
    context: AppContext,
    conversation_id: str,
) -> dict[str, Any]:
    target_id = str(conversation_id or "").strip()
    if not target_id:
        return {}
    for conversation in context.load_edit_conversations():
        if str(conversation.get("id") or "").strip() == target_id:
            return conversation
    return {}


def normalized_context_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        return []
    normalized: list[dict[str, Any]] = []
    for message_index, item in enumerate(
        raw_messages[-IMAGE_AGENT_CONTEXT_MAX_MESSAGES:],
        start=1,
    ):
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or "").strip()
        if not prompt:
            continue
        result_urls = item.get("resultUrls") or item.get("result_urls") or []
        if not isinstance(result_urls, list):
            result_urls = []
        attachments = item.get("attachments") or []
        if not isinstance(attachments, list):
            attachments = []
        image_refs = item.get("imageRefs") or item.get("image_refs") or []
        if not isinstance(image_refs, list):
            image_refs = []
        normalized.append(
            {
                "context_index": message_index,
                "id": str(item.get("id") or "").strip(),
                "prompt": prompt,
                "mode": str(item.get("mode") or "normal").strip(),
                "image_model": str(
                    item.get("imageModel") or item.get("image_model") or ""
                ).strip(),
                "output_resolution": str(
                    item.get("outputResolution") or item.get("output_resolution") or ""
                ).strip(),
                "output_aspect_ratio": str(
                    item.get("outputAspectRatio")
                    or item.get("output_aspect_ratio")
                    or item.get("aspectRatio")
                    or ""
                ).strip(),
                "resolved_size": str(
                    item.get("resolvedSize") or item.get("resolved_size") or ""
                ).strip(),
                "images_per_prompt": item.get("imagesPerPrompt")
                or item.get("images_per_prompt")
                or 1,
                "created_at": str(item.get("createdAt") or item.get("created_at") or "").strip(),
                "run_id": str(item.get("runId") or item.get("run_id") or "").strip(),
                "status": str(item.get("status") or "").strip(),
                "error": str(item.get("error") or "").strip(),
                "assistant_response": str(
                    item.get("assistantResponse")
                    or item.get("assistant_response")
                    or item.get("agentResponseText")
                    or item.get("agent_response_text")
                    or ""
                ).strip(),
                "input_count": item.get("inputCount") or item.get("input_count") or 0,
                "result_urls": [
                    compact_url(url)
                    for url in result_urls[:IMAGE_AGENT_CONTEXT_MAX_RESULT_URLS]
                    if str(url or "").strip()
                ],
                "attachments": [
                    {
                        "name": truncate_text(attachment.get("name"), 120),
                        "src": compact_url(attachment.get("src")),
                    }
                    for attachment in attachments[:IMAGE_AGENT_CONTEXT_MAX_ATTACHMENTS]
                    if isinstance(attachment, dict)
                ],
                "image_refs": [
                    {
                        "id": truncate_text(ref.get("id"), 80),
                        "type": "input"
                        if str(ref.get("type") or "").strip().lower() == "input"
                        else "result",
                        "url": compact_url(ref.get("url")),
                        "thumbnail_url": compact_url(
                            ref.get("thumbnailUrl") or ref.get("thumbnail_url")
                        ),
                        "name": truncate_text(ref.get("name"), 120),
                        "caption": truncate_text(ref.get("caption"), 220),
                        "message_id": truncate_text(
                            ref.get("messageId") or ref.get("message_id"),
                            80,
                        ),
                        "run_id": truncate_text(ref.get("runId") or ref.get("run_id"), 80),
                        "created_at": truncate_text(
                            ref.get("createdAt") or ref.get("created_at"),
                            80,
                        ),
                    }
                    for ref in image_refs[:IMAGE_AGENT_CONTEXT_MAX_IMAGE_REFS]
                    if isinstance(ref, dict)
                    and str(ref.get("id") or "").strip()
                    and (
                        str(ref.get("url") or "").strip()
                        or str(ref.get("thumbnailUrl") or ref.get("thumbnail_url") or "").strip()
                        or str(ref.get("name") or "").strip()
                    )
                ],
            }
        )
    return normalized


def format_context_message(
    item: dict[str, Any],
    index: int,
    *,
    prompt_limit: int,
    include_results: bool,
    include_attachments: bool,
    include_image_refs: bool,
) -> str:
    lines = [
        f"[{index:02d}] {item.get('created_at') or 'unknown time'}",
        f"- mode: {item.get('mode') or 'normal'}",
        f"- status: {item.get('status') or 'unknown'}",
    ]
    if item.get("image_model"):
        lines.append(f"- image_model: {item['image_model']}")
    output_parts = [
        str(item.get("output_resolution") or "").strip(),
        str(item.get("output_aspect_ratio") or "").strip(),
        str(item.get("resolved_size") or "").strip(),
    ]
    output_text = " / ".join(part for part in output_parts if part)
    if output_text:
        lines.append(f"- output: {output_text}")
    if item.get("run_id"):
        lines.append(f"- run_id: {item['run_id']}")
    lines.append(f"- user_prompt: {truncate_text(item.get('prompt'), prompt_limit)}")
    if item.get("error"):
        lines.append(f"- error: {truncate_text(item['error'], 600)}")
    if item.get("assistant_response"):
        lines.append(
            f"- assistant_response: {truncate_text(item['assistant_response'], prompt_limit)}"
        )
    result_urls = item.get("result_urls") if include_results else []
    if isinstance(result_urls, list) and result_urls:
        lines.append(f"- result_images({len(result_urls)}): " + " | ".join(result_urls))
    attachments = item.get("attachments") if include_attachments else []
    if isinstance(attachments, list) and attachments:
        attachment_lines = []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            name = attachment.get("name") or "input image"
            src = attachment.get("src") or ""
            attachment_lines.append(f"{name}{f' -> {src}' if src else ''}")
        if attachment_lines:
            lines.append("- input_images: " + " | ".join(attachment_lines))
    image_refs = item.get("image_refs") if include_image_refs else []
    if isinstance(image_refs, list) and image_refs:
        ref_lines = []
        for ref in image_refs[:IMAGE_AGENT_CONTEXT_MAX_IMAGE_REFS]:
            if not isinstance(ref, dict):
                continue
            ref_id = ref.get("id") or ""
            ref_type = ref.get("type") or "result"
            url = ref.get("url") or ref.get("thumbnail_url") or ""
            label_parts = [
                str(ref.get("name") or "").strip(),
                str(ref.get("caption") or "").strip(),
            ]
            label = " / ".join(part for part in label_parts if part)
            ref_lines.append(
                f"{ref_id} [{ref_type}]"
                f"{f' {label}' if label else ''}"
                f"{f' -> {url}' if url else ''}"
            )
        if ref_lines:
            lines.append("- image_refs: " + " | ".join(ref_lines))
    return "\n".join(lines)


def build_agent_context_text(
    payload: dict[str, Any],
    *,
    char_limit: int,
    recent_full_count: int,
    recent_prompt_limit: int,
    older_prompt_limit: int,
    include_results: bool,
    include_attachments: bool,
    include_image_refs: bool,
) -> tuple[str, dict[str, Any]]:
    messages = normalized_context_messages(payload)
    if not messages:
        return "", {
            "source": "none",
            "message_count": 0,
            "compression": "empty",
            "estimated_tokens": 0,
        }
    older_count = max(0, len(messages) - recent_full_count)
    lines = [
        "Conversation context for the image-generation Agent.",
        f"conversation_id: {payload.get('id') or ''}",
        f"title: {payload.get('title') or ''}",
        f"messages_total: {len(messages)}",
        f"older_messages_compacted: {older_count}",
        "Use this as continuity context. Current uploaded images still take priority for visual identity.",
        "",
        "Messages:",
    ]
    for index, item in enumerate(messages, start=1):
        is_recent = index > older_count
        lines.append(
            format_context_message(
                item,
                index,
                prompt_limit=recent_prompt_limit if is_recent else older_prompt_limit,
                include_results=include_results if is_recent else False,
                include_attachments=include_attachments if is_recent else False,
                include_image_refs=include_image_refs if is_recent else False,
            )
        )
        lines.append("")
    text = "\n".join(lines).strip()
    if len(text) > char_limit:
        text = truncate_text(text, char_limit)
    return text, {
        "source": "conversation",
        "message_count": len(messages),
        "older_message_count": older_count,
        "compression": "compacted" if older_count else "full",
        "char_count": len(text),
        "estimated_tokens": estimated_context_tokens(text),
        "token_limit": IMAGE_AGENT_CONTEXT_TOKEN_LIMIT,
    }


def compact_agent_conversation_context(
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    passes = (
        {
            "char_limit": IMAGE_AGENT_CONTEXT_CHAR_LIMIT,
            "recent_full_count": IMAGE_AGENT_CONTEXT_RECENT_FULL_MESSAGES,
            "recent_prompt_limit": 12_000,
            "older_prompt_limit": 1_200,
            "include_results": True,
            "include_attachments": True,
            "include_image_refs": True,
        },
        {
            "char_limit": IMAGE_AGENT_CONTEXT_CHAR_LIMIT,
            "recent_full_count": 8,
            "recent_prompt_limit": 6_000,
            "older_prompt_limit": 600,
            "include_results": True,
            "include_attachments": False,
            "include_image_refs": True,
        },
        {
            "char_limit": IMAGE_AGENT_CONTEXT_CHAR_LIMIT,
            "recent_full_count": 4,
            "recent_prompt_limit": 2_000,
            "older_prompt_limit": 280,
            "include_results": False,
            "include_attachments": False,
            "include_image_refs": False,
        },
    )
    last_text = ""
    last_meta: dict[str, Any] = {}
    for options in passes:
        text, meta = build_agent_context_text(payload, **options)
        last_text, last_meta = text, meta
        if estimated_context_tokens(text) <= IMAGE_AGENT_CONTEXT_TOKEN_LIMIT:
            return text, meta
    last_meta["compression"] = "hard-truncated"
    return truncate_text(last_text, IMAGE_AGENT_CONTEXT_CHAR_LIMIT), last_meta


def is_local_agent_image_url(value: Any) -> bool:
    text = str(value or "").strip()
    return text.startswith("/data/") or text.startswith("data/")


def path_from_local_agent_image_url(context: AppContext, value: Any) -> Path | None:
    text = str(value or "").strip()
    if not is_local_agent_image_url(text):
        return None
    relative_text = text[6:] if text.startswith("/data/") else text[5:]
    relative_text = relative_text.split("?", 1)[0].split("#", 1)[0]
    relative_text = urllib.parse.unquote(relative_text).replace("\\", "/").lstrip("/")
    if not relative_text:
        return None
    candidate = (context.data_dir / relative_text).resolve()
    try:
        candidate.relative_to(context.data_dir.resolve())
    except ValueError:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    if not guess_mime_type(candidate).startswith("image/"):
        return None
    return candidate


def build_agent_context_image_refs(
    context: AppContext,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    messages = normalized_context_messages(payload)
    refs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for message_position, message in enumerate(messages, start=1):
        message_refs = message.get("image_refs")
        if not isinstance(message_refs, list):
            continue
        for ref in message_refs:
            if not isinstance(ref, dict):
                continue
            raw_id = str(ref.get("id") or "").strip()
            if not raw_id or raw_id in seen_ids:
                continue
            image_path = (
                path_from_local_agent_image_url(context, ref.get("url"))
                or path_from_local_agent_image_url(context, ref.get("thumbnail_url"))
            )
            if not image_path:
                continue
            seen_ids.add(raw_id)
            refs.append(
                {
                    "id": raw_id,
                    "type": str(ref.get("type") or "result").strip() or "result",
                    "path": image_path,
                    "name": str(ref.get("name") or image_path.name).strip(),
                    "caption": str(ref.get("caption") or "").strip(),
                    "message_index": message_position,
                    "message_id": str(message.get("id") or ref.get("message_id") or "").strip(),
                    "run_id": str(message.get("run_id") or ref.get("run_id") or "").strip(),
                    "created_at": str(
                        message.get("created_at") or ref.get("created_at") or ""
                    ).strip(),
                    "prompt": str(message.get("prompt") or "").strip(),
                }
            )
    return refs[-IMAGE_AGENT_CONTEXT_MAX_IMAGE_REFS:]


def select_agent_visual_context_refs(
    refs: list[dict[str, Any]],
    *,
    max_count: int = IMAGE_AGENT_CONTEXT_MAX_VISUAL_REFS,
) -> list[dict[str, Any]]:
    if max_count <= 0:
        return []
    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    latest_message_index = None
    for ref in reversed(refs):
        if ref.get("path") and ref.get("message_index"):
            latest_message_index = ref.get("message_index")
            break
    candidates = [
        ref for ref in refs if latest_message_index is not None and ref.get("message_index") == latest_message_index
    ]
    if not candidates:
        candidates = list(refs)
    type_order = {"input": 0, "result": 1}
    candidates = sorted(
        candidates,
        key=lambda ref: (type_order.get(str(ref.get("type") or ""), 2), str(ref.get("id") or "")),
    )
    for ref in candidates:
        ref_id = str(ref.get("id") or "").strip()
        if not ref_id or ref_id in seen_ids:
            continue
        selected.append(ref)
        seen_ids.add(ref_id)
        if len(selected) >= max_count:
            break
    return selected


def visual_context_budget(input_images: list[Path]) -> int:
    return max(0, min(IMAGE_AGENT_CONTEXT_MAX_VISUAL_REFS, MAX_IMAGE_EDIT_INPUT_IMAGES - len(input_images)))


def resolve_agent_conversation_context(
    context: AppContext,
    options: ImageAgentOptions,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    payload = parse_agent_conversation_context_payload(options.conversation_context)
    source = "request"
    if not payload and options.conversation_id:
        payload = find_saved_conversation(context, options.conversation_id)
        source = "saved"
    if not payload:
        return "", {
            "source": "none",
            "message_count": 0,
            "compression": "empty",
            "estimated_tokens": 0,
            "token_limit": IMAGE_AGENT_CONTEXT_TOKEN_LIMIT,
        }, []
    text, meta = compact_agent_conversation_context(payload)
    image_refs = build_agent_context_image_refs(context, payload)
    meta["source"] = source
    meta["image_ref_count"] = len(image_refs)
    meta["visual_ref_limit"] = IMAGE_AGENT_CONTEXT_MAX_VISUAL_REFS
    return text, meta, image_refs


def image_agent_user_content(
    *,
    user_prompt: str,
    input_images: list[Path],
    context_image_refs: list[dict[str, Any]] | None = None,
    selected_image_model: str,
    effective_image_model: str,
    output_resolution: str,
    output_aspect_ratio: str,
    resolved_size: str,
    allowed_resolutions: list[str] | None,
    default_resolution: str | None,
    conversation_context: str,
    plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context_image_refs = context_image_refs or []
    visual_context_refs = (
        select_agent_visual_context_refs(
            context_image_refs,
            max_count=visual_context_budget(input_images),
        )
        if is_referential_image_followup(user_prompt)
        else []
    )
    text_lines = [
        "用户需求:",
        user_prompt.strip(),
    ]
    if conversation_context:
        text_lines.extend(
            [
                "",
                "历史会话上下文（后端已按上下文窗口自动压缩）:",
                conversation_context,
            ]
        )
    text_lines.extend(
        [
        "",
        "后端强约束:",
        f"- 生图逻辑模型: {selected_image_model}",
        f"- 实际请求模型: {effective_image_model}",
        f"- 分辨率: {output_resolution if output_resolution != 'agent' else '由 Agent 从允许值中选择'}",
        f"- 比例: {output_aspect_ratio if output_aspect_ratio != 'agent' else '由 Agent 从允许值中选择'}",
        f"- 最终尺寸/尺寸标签: {resolved_size or '由后端根据模型规则决定'}",
        f"- 参考图数量: {len(input_images)}",
        "",
        "Agent 可选输出规格:",
        image_agent_allowed_output_text(
            selected_image_model,
            allowed_resolutions=allowed_resolutions,
            default_resolution=default_resolution,
        ),
        ]
    )
    if input_images:
        text_lines.extend(["", "<input_images>"])
        for index, image_path in enumerate(input_images, start=1):
            text_lines.append(
                f'  <image file_id="reference_image_{index}" name="{image_path.name}" />'
            )
        text_lines.append("</input_images>")
    if context_image_refs:
        text_lines.extend(
            [
                "",
                "<context_image_refs>",
            ]
        )
        visual_ids = {str(ref.get("id") or "") for ref in visual_context_refs}
        for ref in context_image_refs:
            ref_id = str(ref.get("id") or "").strip()
            if not ref_id:
                continue
            text_lines.append(
                "  "
                f'<image_ref file_id="{xml_attr(ref_id)}" '
                f'type="{xml_attr(ref.get("type") or "result")}" '
                f'message_index="{xml_attr(ref.get("message_index") or "")}" '
                f'run_id="{xml_attr(ref.get("run_id") or "")}" '
                f'visual_attached="{"true" if ref_id in visual_ids else "false"}" '
                f'name="{xml_attr(truncate_text(ref.get("name"), 80))}" '
                f'caption="{xml_attr(truncate_text(ref.get("caption"), 160))}" />'
            )
        text_lines.append("</context_image_refs>")
        text_lines.extend(
            [
                "Use context_image_refs as an index of prior input/result images. "
                "When the user says phrases like this image, previous one, just now, "
                "or says the effect is not right, resolve the most likely target from "
                "the latest relevant message and use its input refs and result refs together. Only refs with "
                'visual_attached="true" are visually attached in this request; older '
                "refs are index-only continuity metadata.",
                "Current uploaded reference_image_* images still have highest priority "
                "when the user explicitly uploads images in the current turn.",
            ]
        )
    if plan is not None:
        text_lines.extend(
            [
                "",
                "已确认执行计划 JSON:",
                json.dumps(plan, ensure_ascii=False, indent=2),
            ]
        )
    user_content: list[dict[str, Any]] = [{"type": "text", "text": "\n".join(text_lines)}]
    for index, image_path in enumerate(input_images, start=1):
        user_content.extend(
            [
                {"type": "text", "text": f"reference_image_{index}"},
                {
                    "type": "image_url",
                    "image_url": {"url": encode_image_as_data_url(image_path)},
                },
            ]
        )
    for ref in visual_context_refs:
        ref_id = str(ref.get("id") or "").strip()
        image_path = ref.get("path")
        if not ref_id or not isinstance(image_path, Path):
            continue
        user_content.extend(
            [
                {"type": "text", "text": ref_id},
                {
                    "type": "image_url",
                    "image_url": {"url": encode_image_as_data_url(image_path)},
                },
            ]
        )
    return user_content


def image_agent_chat_payload(
    settings: Settings,
    *,
    system_prompt: str,
    user_prompt: str,
    input_images: list[Path],
    context_image_refs: list[dict[str, Any]] | None = None,
    selected_image_model: str,
    effective_image_model: str,
    output_resolution: str,
    output_aspect_ratio: str,
    resolved_size: str,
    allowed_resolutions: list[str] | None,
    default_resolution: str | None,
    max_tokens: int,
    conversation_context: str,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": settings.image_agent_model or DEFAULT_IMAGE_AGENT_MODEL,
        "stream": False,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": image_agent_user_content(
                    user_prompt=user_prompt,
                    input_images=input_images,
                    context_image_refs=context_image_refs,
                    selected_image_model=selected_image_model,
                    effective_image_model=effective_image_model,
                    output_resolution=output_resolution,
                    output_aspect_ratio=output_aspect_ratio,
                    resolved_size=resolved_size,
                    allowed_resolutions=allowed_resolutions,
                    default_resolution=default_resolution,
                    conversation_context=conversation_context,
                    plan=plan,
                ),
            },
        ],
    }
    if settings.reasoning_wire_format == "reasoning_effort":
        payload["reasoning_effort"] = settings.reasoning_effort
    else:
        payload["reasoning"] = {"effort": settings.reasoning_effort}
    return payload


def image_agent_write_plan_tool_spec(
    *,
    allowed_resolutions: list[str] | None = None,
    allowed_aspect_ratios: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "write_plan",
            "description": (
                "Write the execution plan before image generation. The plan should be "
                "friendly to show to the user and include backend-executable output specs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Short plan summary in the user's language.",
                    },
                    "needs_image": {
                        "type": "boolean",
                        "description": (
                            "True only when this turn should generate or edit images. "
                            "False for normal chat or text-only answers."
                        ),
                    },
                    "response_text": {
                        "type": "string",
                        "description": (
                            "Complete user-facing answer when needs_image is false. "
                            "Leave empty when image generation is needed."
                        ),
                    },
                    "image_count": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": MAX_IMAGE_AGENT_REQUEST_COUNT,
                        "description": "Number of images requested by the user. Use 0 when needs_image is false.",
                    },
                    "output_resolution": {
                        "type": "string",
                        "description": "One allowed output resolution such as 1k, 2k, or 4k.",
                        "enum": allowed_resolutions or image_agent_allowed_resolutions(
                            IMAGE_MODEL_GPT_IMAGE_2
                        ),
                    },
                    "output_aspect_ratio": {
                        "type": "string",
                        "description": "One allowed aspect ratio such as 1:1, 3:4, 4:3, 9:16, or 16:9.",
                        "enum": allowed_aspect_ratios
                        or image_agent_allowed_aspect_ratios(IMAGE_MODEL_GPT_IMAGE_2),
                    },
                    "reference_usage": {
                        "type": "string",
                        "description": "How uploaded references should be used.",
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["title"],
                        },
                    },
                    "deliverables": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["index", "title"],
                        },
                    },
                    "notes": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "summary",
                    "needs_image",
                    "response_text",
                    "image_count",
                    "output_resolution",
                    "output_aspect_ratio",
                    "steps",
                    "deliverables",
                ],
            },
        },
    }


def image_agent_generate_tool_spec(
    image_model: str,
    *,
    allowed_resolutions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "generate_image_by_selected_model",
            "description": (
                "Prepare one image generation call using the backend-selected image model. "
                "Call this tool once per planned image."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short title for this deliverable in the user's language.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Detailed English image generation prompt.",
                    },
                    "output_resolution": {
                        "type": "string",
                        "enum": allowed_resolutions
                        or image_agent_allowed_resolutions(image_model),
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": image_agent_allowed_aspect_ratios(image_model),
                    },
                    "input_images": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional reference image IDs, e.g. reference_image_1 "
                            "from <input_images> or m03_result_01 from "
                            "<context_image_refs>. Use the minimal relevant subset."
                        ),
                    },
                },
                "required": ["title", "prompt", "output_resolution", "aspect_ratio"],
            },
        },
    }


def image_agent_tool_payload(
    payload: dict[str, Any],
    *,
    tools: list[dict[str, Any]],
    tool_name: str | None = None,
) -> dict[str, Any]:
    next_payload = dict(payload)
    next_payload["tools"] = tools
    if tool_name:
        next_payload["tool_choice"] = {
            "type": "function",
            "function": {"name": tool_name},
        }
    else:
        next_payload["tool_choice"] = "auto"
    return next_payload


def image_agent_endpoint_url(settings: Settings) -> str:
    endpoint_type = normalize_llm_endpoint_type(settings.image_agent_endpoint_type)
    suffix = (
        "/v1/responses"
        if endpoint_type == LLM_ENDPOINT_RESPONSES
        else "/v1/chat/completions"
    )
    return f"{settings.image_agent_api_base}{suffix}"


def chat_content_part_to_response_part(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    item_type = item.get("type")
    if item_type == "text":
        return {"type": "input_text", "text": str(item.get("text") or "")}
    if item_type == "image_url":
        image_url = item.get("image_url")
        if isinstance(image_url, dict):
            url = image_url.get("url")
        else:
            url = image_url
        return {"type": "input_image", "image_url": str(url or ""), "detail": "auto"}
    return dict(item)


def chat_message_to_response_input(message: dict[str, Any]) -> dict[str, Any]:
    role = str(message.get("role") or "user").strip() or "user"
    if role == "system":
        role = "developer"
    content = message.get("content")
    if isinstance(content, list):
        response_content = [chat_content_part_to_response_part(item) for item in content]
    else:
        response_content = [
            {"type": "input_text", "text": str(content or "")},
        ]
    return {"role": role, "content": response_content}


def response_tool_spec_from_chat_tool(tool: dict[str, Any]) -> dict[str, Any]:
    if tool.get("type") != "function":
        return dict(tool)
    function = tool.get("function")
    if not isinstance(function, dict):
        return dict(tool)
    return {
        "type": "function",
        "name": str(function.get("name") or ""),
        "description": str(function.get("description") or ""),
        "parameters": function.get("parameters") or {"type": "object"},
    }


def response_tool_choice_from_chat(tool_choice: Any) -> Any:
    if tool_choice in (None, "auto", "none", "required"):
        return tool_choice
    if isinstance(tool_choice, dict):
        function = tool_choice.get("function")
        if isinstance(function, dict) and function.get("name"):
            return {
                "type": "function",
                "name": str(function.get("name") or ""),
            }
    return tool_choice


def responses_payload_from_chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    response_payload: dict[str, Any] = {
        "model": payload.get("model"),
        "input": [
            chat_message_to_response_input(message)
            for message in payload.get("messages", [])
            if isinstance(message, dict)
        ],
    }
    if payload.get("max_tokens"):
        response_payload["max_output_tokens"] = payload["max_tokens"]
    if payload.get("reasoning_effort") and payload.get("reasoning_effort") != "none":
        response_payload["reasoning"] = {"effort": payload["reasoning_effort"]}
    elif isinstance(payload.get("reasoning"), dict):
        reasoning = payload["reasoning"]
        if reasoning.get("effort") != "none":
            response_payload["reasoning"] = reasoning
    tools = payload.get("tools")
    if isinstance(tools, list) and tools:
        response_payload["tools"] = [
            response_tool_spec_from_chat_tool(tool)
            for tool in tools
            if isinstance(tool, dict)
        ]
        if "tool_choice" in payload:
            response_payload["tool_choice"] = response_tool_choice_from_chat(
                payload.get("tool_choice")
            )
    return response_payload


def image_agent_plain_fallback_payload(payload: dict[str, Any]) -> dict[str, Any]:
    fallback = dict(payload)
    fallback.pop("tools", None)
    fallback.pop("tool_choice", None)
    fallback.pop("_endpoint_type", None)
    return fallback


def tool_call_fallback_payload(payload: dict[str, Any]) -> dict[str, Any]:
    fallback = dict(payload)
    fallback.pop("tools", None)
    fallback.pop("tool_choice", None)
    return fallback


def is_tool_call_compat_error(error: AppError) -> bool:
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "tool_choice",
            "tools",
            "function_call",
            "function calling",
            "unsupported parameter",
            "unknown parameter",
        )
    )


def request_image_agent_chat(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    connect_timeout_seconds: int,
    read_timeout_seconds: int,
    retry_count: int,
    logger: AppLogger,
    label: str,
    request_log_path: Path,
    response_log_path: Path,
    use_system_proxy: bool = False,
) -> Any:
    request_payload = dict(payload)
    request_payload.pop("_endpoint_type", None)
    try:
        return request_json(
            url,
            request_payload,
            api_key=api_key,
            idempotency_key=None,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            retry_count=retry_count,
            logger=logger,
            label=label,
            request_log_path=request_log_path,
            response_log_path=response_log_path,
            use_system_proxy=use_system_proxy,
        )
    except AppError as exc:
        if "tools" not in payload or not is_tool_call_compat_error(exc):
            raise
        logger.log(f"{label}: tool-call request failed, retrying plain fallback: {exc}")
        return request_json(
            url,
            image_agent_plain_fallback_payload(payload),
            api_key=api_key,
            idempotency_key=None,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            retry_count=retry_count,
            logger=logger,
            label=f"{label} fallback",
            request_log_path=request_log_path.with_name(
                f"{request_log_path.stem}.fallback{request_log_path.suffix}"
            ),
            response_log_path=response_log_path.with_name(
                f"{response_log_path.stem}.fallback{response_log_path.suffix}"
            ),
            use_system_proxy=use_system_proxy,
        )


def request_image_agent_llm(
    settings: Settings,
    payload: dict[str, Any],
    *,
    api_key: str,
    connect_timeout_seconds: int,
    read_timeout_seconds: int,
    retry_count: int,
    logger: AppLogger,
    label: str,
    request_log_path: Path,
    response_log_path: Path,
) -> Any:
    endpoint_type = normalize_llm_endpoint_type(settings.image_agent_endpoint_type)
    url = image_agent_endpoint_url(settings)
    if endpoint_type == LLM_ENDPOINT_RESPONSES:
        payload = responses_payload_from_chat_payload(payload)
        payload["_endpoint_type"] = LLM_ENDPOINT_RESPONSES
        logger.log(f"{label}: 使用 /v1/responses")
    else:
        payload = dict(payload)
        payload["_endpoint_type"] = LLM_ENDPOINT_CHAT_COMPLETIONS
        logger.log(f"{label}: 使用 /v1/chat/completions")
    return request_image_agent_chat(
        url,
        payload,
        api_key=api_key,
        connect_timeout_seconds=connect_timeout_seconds,
        read_timeout_seconds=read_timeout_seconds,
        retry_count=retry_count,
        logger=logger,
        label=label,
        request_log_path=request_log_path,
        response_log_path=response_log_path,
        use_system_proxy=settings.use_system_proxy,
    )


def first_chat_message(response_json: Any) -> dict[str, Any]:
    try:
        message = response_json["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AppError("提示词接口返回里没有找到 message。") from exc
    if not isinstance(message, dict):
        raise AppError("提示词接口返回里的 message 不是对象。")
    return message


def parse_tool_call_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not isinstance(raw_arguments, str):
        return {}
    text = raw_arguments.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            payload = json.loads(extract_json_object_text(text))
        except Exception:
            return {}
    return payload if isinstance(payload, dict) else {}


def extract_chat_tool_calls(response_json: Any) -> list[dict[str, Any]]:
    message = first_chat_message(response_json)
    raw_calls = message.get("tool_calls")
    calls: list[dict[str, Any]] = []
    if isinstance(raw_calls, list):
        for raw_call in raw_calls:
            if not isinstance(raw_call, dict):
                continue
            function = raw_call.get("function")
            if not isinstance(function, dict):
                continue
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            calls.append(
                {
                    "id": str(raw_call.get("id") or ""),
                    "name": name,
                    "arguments": parse_tool_call_arguments(function.get("arguments")),
                }
            )
    function_call = message.get("function_call")
    if isinstance(function_call, dict):
        name = str(function_call.get("name") or "").strip()
        if name:
            calls.append(
                {
                    "id": "",
                    "name": name,
                    "arguments": parse_tool_call_arguments(function_call.get("arguments")),
                }
            )
    return calls


def iter_response_output_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        items = value.get("output")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def extract_response_tool_calls(response_json: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in iter_response_output_items(response_json):
        item_type = str(item.get("type") or "").strip()
        if item_type not in {"function_call", "tool_call"}:
            continue
        name = str(item.get("name") or "").strip()
        if not name and isinstance(item.get("function"), dict):
            name = str(item["function"].get("name") or "").strip()
        if not name:
            continue
        raw_arguments = item.get("arguments")
        if raw_arguments is None and isinstance(item.get("function"), dict):
            raw_arguments = item["function"].get("arguments")
        calls.append(
            {
                "id": str(item.get("id") or item.get("call_id") or ""),
                "name": name,
                "arguments": parse_tool_call_arguments(raw_arguments),
            }
        )
    return calls


def extract_llm_tool_calls(response_json: Any) -> list[dict[str, Any]]:
    response_calls = extract_response_tool_calls(response_json)
    if response_calls:
        return response_calls
    try:
        return extract_chat_tool_calls(response_json)
    except AppError:
        return []


def extract_message_text_optional(response_json: Any) -> str:
    try:
        return extract_message_text(response_json)
    except AppError:
        return ""


def extract_first_tool_arguments(
    response_json: Any,
    tool_name: str,
) -> dict[str, Any] | None:
    for call in extract_llm_tool_calls(response_json):
        if call["name"] == tool_name:
            arguments = call.get("arguments")
            return arguments if isinstance(arguments, dict) else {}
    return None


def summarize_llm_response_shape(response_json: Any) -> dict[str, Any]:
    if not isinstance(response_json, dict):
        return {"type": type(response_json).__name__}
    output_items = iter_response_output_items(response_json)
    output_types = [
        str(item.get("type") or "").strip() or "<missing>"
        for item in output_items
    ]
    tool_names = [
        str(call.get("name") or "").strip()
        for call in extract_llm_tool_calls(response_json)
        if str(call.get("name") or "").strip()
    ]
    choices = response_json.get("choices")
    choice_count = len(choices) if isinstance(choices, list) else 0
    return {
        "top_level_keys": sorted(str(key) for key in response_json.keys()),
        "status": response_json.get("status"),
        "error": response_json.get("error"),
        "incomplete_details": response_json.get("incomplete_details"),
        "output_count": len(output_items),
        "output_types": output_types,
        "tool_names": tool_names,
        "has_output_text": bool(
            isinstance(response_json.get("output_text"), str)
            and response_json.get("output_text", "").strip()
        ),
        "choice_count": choice_count,
    }


def format_llm_response_shape(response_json: Any) -> str:
    return json.dumps(
        summarize_llm_response_shape(response_json),
        ensure_ascii=False,
        sort_keys=True,
    )


def extract_response_text(response_json: Any) -> str:
    output_text = response_json.get("output_text") if isinstance(response_json, dict) else None
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    chunks: list[str] = []
    for output_item in iter_response_output_items(response_json):
        content = output_item.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            for key in ("text", "value", "content"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    chunks.append(value.strip())
                    break
    text = "\n".join(chunks).strip()
    if text:
        return text
    raise AppError("Responses 接口返回里没有找到可解析文本。")


def extract_message_text(response_json: Any) -> str:
    try:
        return extract_response_text(response_json)
    except AppError:
        pass
    try:
        content = response_json["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AppError("提示词接口返回里没有找到 message.content。") from exc
    if isinstance(content, str):
        text = content.strip()
        if text:
            return text
    elif isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    chunks.append(item.strip())
                continue
            if isinstance(item, dict):
                for candidate in (item.get("text"), item.get("content"), item.get("value")):
                    if isinstance(candidate, str) and candidate.strip():
                        chunks.append(candidate.strip())
                        break
        text = "\n".join(chunks).strip()
        if text:
            return text
    raise AppError("提示词接口返回里的 message.content 不是可解析的文本。")


def extract_json_object_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned

    start = cleaned.find("{")
    if start < 0:
        raise AppError("Agent 返回内容里没有 JSON 对象。")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : index + 1]
    raise AppError("Agent 返回的 JSON 对象不完整。")


def parse_json_object_text(text: str, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(extract_json_object_text(text))
    except json.JSONDecodeError as exc:
        raise AppError(f"{label} 返回的 JSON 无法解析：{exc}") from exc
    if not isinstance(payload, dict):
        raise AppError(f"{label} 必须返回 JSON 对象。")
    return payload


CHINESE_SMALL_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def parse_small_chinese_number(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text in CHINESE_SMALL_NUMBERS:
        return CHINESE_SMALL_NUMBERS[text]
    if text.startswith("十") and len(text) == 2:
        unit = CHINESE_SMALL_NUMBERS.get(text[1])
        return 10 + unit if unit else None
    if len(text) == 2 and text.endswith("十"):
        ten = CHINESE_SMALL_NUMBERS.get(text[0])
        return ten * 10 if ten else None
    if len(text) == 3 and text[1] == "十":
        ten = CHINESE_SMALL_NUMBERS.get(text[0])
        unit = CHINESE_SMALL_NUMBERS.get(text[2])
        if ten and unit:
            return ten * 10 + unit
    return None


def infer_agent_image_count_from_text(text: str) -> int:
    raw_text = str(text or "")
    patterns = (
        r"(?<![\w-])(\d{1,3})\s*(?:张|幅|个|套|条|页|组|p|P|images?|pictures?|pics?|renders?)",
        r"(?:生成|做|出|需要|要|produce|generate|make|create)\s*(\d{1,3})\s*(?:张|幅|个|套|条|页|组|p|P|images?|pictures?|pics?|renders?)?",
    )
    for pattern in patterns:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE)
        if match:
            return bounded_agent_image_count(match.group(1))
    chinese_match = re.search(r"([一二两三四五六七八九十]{1,3})\s*(?:张|幅|个|套|条|页|组)", raw_text)
    if chinese_match:
        parsed = parse_small_chinese_number(chinese_match.group(1))
        if parsed:
            return bounded_agent_image_count(parsed)
    return 1


def bounded_agent_image_count(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(MAX_IMAGE_AGENT_REQUEST_COUNT, parsed))


def bounded_agent_image_count_or_zero(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    return max(0, min(MAX_IMAGE_AGENT_REQUEST_COUNT, parsed))


def resolve_image_agent_request_config(
    plan: dict[str, Any],
    *,
    image_model: str,
    settings: Settings,
    allowed_resolutions: list[str] | None = None,
    input_images: list[Path] | None = None,
    logger: Any | None = None,
) -> dict[str, str]:
    try:
        resolution = normalize_output_resolution(plan.get("output_resolution"))
    except AppError as exc:
        raise AppError("Agent 规划阶段返回了无效的分辨率。") from exc
    try:
        aspect_ratio = normalize_output_aspect_ratio(plan.get("output_aspect_ratio"))
    except AppError as exc:
        raise AppError("Agent 规划阶段返回了无效的比例。") from exc

    allowed_resolutions = set(
        allowed_resolutions or image_agent_allowed_resolutions(image_model)
    )
    allowed_ratios = set(image_agent_allowed_aspect_ratios(image_model))
    if resolution not in allowed_resolutions:
        raise AppError(
            f"Agent 规划阶段返回的分辨率 {resolution or '空'} 不可用，可选：{', '.join(sorted(allowed_resolutions))}。"
        )
    if aspect_ratio not in allowed_ratios:
        raise AppError(
            f"Agent 规划阶段返回的比例 {aspect_ratio or '空'} 不适用于当前模型，可选：{', '.join(allowed_ratios)}。"
        )
    return resolve_image_request_config(
        output_resolution=resolution,
        output_aspect_ratio=aspect_ratio,
        settings=settings,
        image_model=image_model,
        input_images=input_images,
        logger=logger,
    )


def resolve_image_agent_prompt_item_config(
    prompt_item: dict[str, Any],
    *,
    default_request_config: dict[str, str],
    image_model: str,
    settings: Settings,
    allowed_resolutions: list[str] | None = None,
    input_images: list[Path] | None = None,
    logger: Any | None = None,
) -> dict[str, str]:
    resolution = (
        prompt_item.get("output_resolution")
        or default_request_config.get("output_resolution")
        or "1k"
    )
    aspect_ratio = (
        prompt_item.get("output_aspect_ratio")
        or prompt_item.get("aspect_ratio")
        or default_request_config.get("output_aspect_ratio")
        or "1:1"
    )
    return resolve_image_agent_request_config(
        {"output_resolution": resolution, "output_aspect_ratio": aspect_ratio},
        image_model=image_model,
        settings=settings,
        allowed_resolutions=allowed_resolutions,
        input_images=input_images,
        logger=logger,
    )


def enrich_image_agent_prompt_items(
    prompt_items: list[dict[str, Any]],
    *,
    default_request_config: dict[str, str],
    image_model: str,
    settings: Settings,
    allowed_resolutions: list[str] | None = None,
    input_image_registry: dict[str, Path] | None = None,
    user_prompt: str = "",
    current_input_images: list[Path] | None = None,
    context_image_refs: list[dict[str, Any]] | None = None,
    logger: Any | None = None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for index, item in enumerate(prompt_items, start=1):
        item_input_images: list[Path] = []
        if input_image_registry:
            item_input_images = select_agent_render_input_images(
                item,
                user_prompt=user_prompt,
                current_input_images=current_input_images or [],
                context_image_refs=context_image_refs or [],
                input_image_registry=input_image_registry,
            )
        request_config = resolve_image_agent_prompt_item_config(
            item,
            default_request_config=default_request_config,
            image_model=image_model,
            settings=settings,
            allowed_resolutions=allowed_resolutions,
            input_images=item_input_images,
            logger=logger,
        )
        next_item = dict(item)
        next_item["index"] = index
        next_item["output_resolution"] = request_config["output_resolution"]
        next_item["output_aspect_ratio"] = request_config["output_aspect_ratio"]
        next_item["resolved_size"] = request_config["size"]
        next_item["output_label"] = request_config["label"]
        enriched.append(next_item)
    return enriched


def summarize_agent_request_config(
    prompt_items: list[dict[str, Any]],
    fallback_request_config: dict[str, str],
) -> dict[str, str]:
    if not prompt_items:
        return fallback_request_config
    resolutions = {
        str(item.get("output_resolution") or "").strip()
        for item in prompt_items
        if str(item.get("output_resolution") or "").strip()
    }
    ratios = {
        str(item.get("output_aspect_ratio") or "").strip()
        for item in prompt_items
        if str(item.get("output_aspect_ratio") or "").strip()
    }
    sizes = {
        str(item.get("resolved_size") or "").strip()
        for item in prompt_items
        if str(item.get("resolved_size") or "").strip()
    }
    labels = {
        str(item.get("output_label") or "").strip()
        for item in prompt_items
        if str(item.get("output_label") or "").strip()
    }
    if len(resolutions) == 1 and len(ratios) == 1 and len(sizes) == 1:
        return {
            "output_resolution": next(iter(resolutions)),
            "output_aspect_ratio": next(iter(ratios)),
            "size": next(iter(sizes)),
            "label": next(iter(labels)) if len(labels) == 1 else "Agent 自动",
        }
    return {
        "output_resolution": "agent",
        "output_aspect_ratio": "agent",
        "size": "agent",
        "label": "Agent 自动",
    }


NUMBERED_PROMPT_HEADER_PATTERN = re.compile(
    r"""
    ^\s*
    (?:[-*>\s#`]*\s*)?
    (?:prompt\s*)?
    \**\s*
    (?P<number>\d{1,3})
    \s*\**\s*
    (?:
        [\.\):：、-]\s*(?P<inline>.*)
    )?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_numbered_prompt_sections(text: str) -> list[str]:
    prompts: list[str] = []
    current_lines: list[str] = []
    current_number: str | None = None
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    for raw_line in normalized.split("\n"):
        header = NUMBERED_PROMPT_HEADER_PATTERN.match(raw_line)
        if header:
            if current_number is not None:
                prompt_text = "\n".join(current_lines).strip()
                if prompt_text:
                    prompts.append(prompt_text)
            current_number = header.group("number")
            current_lines = []
            inline_text = (header.group("inline") or "").strip()
            if inline_text:
                current_lines.append(inline_text)
            continue
        if current_number is not None:
            current_lines.append(raw_line)

    if current_number is not None:
        prompt_text = "\n".join(current_lines).strip()
        if prompt_text:
            prompts.append(prompt_text)
    return prompts


def extract_numbered_prompts(text: str, expected_count: int) -> list[str]:
    prompts = extract_numbered_prompt_sections(text)
    if len(prompts) != expected_count:
        pattern = re.compile(
            r"(?ms)^\s*(\d{1,3})[\.\):：、-]\s*(.*?)(?=^\s*\d{1,3}[\.\):：、-]\s*|\Z)"
        )
        matches = pattern.findall(text)
        prompts = [body.strip() for _, body in matches if body.strip()]
    if len(prompts) == expected_count:
        return prompts
    if expected_count == 1 and text.strip():
        return [
            re.sub(
                r"^\s*(?:prompt\s*)?\d{1,3}\s*(?:[\.\):：、-]\s*)?",
                "",
                text.strip(),
                flags=re.IGNORECASE,
            )
        ]
    raise AppError(
        f"预期 {expected_count} 条提示词，但实际解析到 {len(prompts)} 条。"
    )


def format_prompt_lines(prompts: list[str]) -> str:
    width = max(2, len(str(len(prompts))))
    return "\n\n".join(
        f"{index:0{width}d}. {prompt}" for index, prompt in enumerate(prompts, start=1)
    ) + "\n"


def extract_render_payloads(response_json: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []

    def normalized_string(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    def is_remote_image_url(value: str) -> bool:
        if not value:
            return False
        parsed = urllib.parse.urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def append_payload(kind: str, raw_value: Any) -> None:
        normalized = normalized_string(raw_value)
        if not normalized:
            return
        if kind == "url" and not is_remote_image_url(normalized):
            return
        payloads.append({"kind": kind, "value": normalized})

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            append_payload("b64_json", value.get("b64_json"))
            append_payload("url", value.get("url"))
            inline_data = value.get("inlineData") or value.get("inline_data")
            if isinstance(inline_data, dict):
                mime_type = str(inline_data.get("mimeType") or inline_data.get("mime_type") or "")
                if not mime_type or mime_type.startswith("image/"):
                    append_payload("base64", inline_data.get("data"))
            image_value = normalized_string(value.get("image"))
            if image_value:
                if image_value.startswith(("http://", "https://")):
                    append_payload("url", image_value)
                elif image_value.startswith("data:") and ";base64," in image_value:
                    append_payload("base64", image_value.split(";base64,", maxsplit=1)[1])
                else:
                    append_payload("base64", image_value)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(response_json)
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for payload in payloads:
        marker = (payload["kind"], payload["value"])
        if marker not in seen:
            seen.add(marker)
            unique.append(payload)
    return unique


def image_dimensions(image_bytes: bytes) -> tuple[int, int] | None:
    if len(image_bytes) >= 24 and image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack(">II", image_bytes[16:24])
    if len(image_bytes) >= 2 and image_bytes[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(image_bytes):
            if image_bytes[index] != 0xFF:
                index += 1
                continue
            marker = image_bytes[index + 1]
            if 0xC0 <= marker <= 0xC3:
                height = struct.unpack(">H", image_bytes[index + 5:index + 7])[0]
                width = struct.unpack(">H", image_bytes[index + 7:index + 9])[0]
                return width, height
            block_length = struct.unpack(">H", image_bytes[index + 2:index + 4])[0]
            index += 2 + block_length
    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return None
    return None


def reduced_ratio_label(width: int, height: int) -> str:
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def image_file_dimensions(
    image_path: Path,
    *,
    logger: Any | None = None,
) -> tuple[int, int] | None:
    source = Path(image_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        return None
    try:
        try:
            from PIL import Image, ImageOps
        except ImportError:
            return image_dimensions(source.read_bytes())
        with Image.open(source) as image:
            normalized = ImageOps.exif_transpose(image)
            return normalized.size
    except Exception as exc:
        if logger is not None:
            logger.log(f"读取输入图尺寸失败：{source} -> {exc}")
        try:
            return image_dimensions(source.read_bytes())
        except Exception:
            return None


def is_direct_gpt_image_size(width: int, height: int) -> bool:
    pixel_count = width * height
    return (
        width > 0
        and height > 0
        and width % IMAGE_SIZE_MULTIPLE == 0
        and height % IMAGE_SIZE_MULTIPLE == 0
        and width <= IMAGE_SIZE_MAX_EDGE
        and height <= IMAGE_SIZE_MAX_EDGE
        and pixel_count <= IMAGE_SIZE_MAX_PIXELS
    )


def image_size_resolution_bucket(width: int, height: int) -> str:
    longest_edge = max(width, height)
    if longest_edge <= OUTPUT_RESOLUTION_LONG_EDGE["1k"]:
        return "1k"
    if longest_edge <= OUTPUT_RESOLUTION_LONG_EDGE["2k"]:
        return "2k"
    return "4k"


def closest_output_aspect_ratio_for_size(
    width: int,
    height: int,
    *,
    allowed_ratios: list[str] | tuple[str, ...] | None = None,
) -> str:
    source_ratio = width / height
    candidates = [
        item
        for item in (allowed_ratios or OUTPUT_ASPECT_RATIO_OPTIONS)
        if item and item != "auto"
    ]
    best_ratio = "1:1"
    best_distance = float("inf")
    for candidate in candidates:
        try:
            candidate_width, candidate_height = parse_aspect_ratio_pair(candidate)
        except Exception:
            continue
        candidate_ratio = candidate_width / candidate_height
        distance = abs(math.log(source_ratio / candidate_ratio))
        if distance < best_distance:
            best_ratio = candidate
            best_distance = distance
    return best_ratio


def extension_from_url(url: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix if suffix else ""


def extension_from_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    base_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    return mimetypes.guess_extension(base_type) or ""


def extension_from_bytes(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if image_bytes.startswith(b"\xff\xd8"):
        return ".jpg"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return ".webp"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return ".gif"
    return ".png"


def thumbnail_path_for_image(image_path: Path) -> Path:
    return image_path.parent / "_thumbs" / f"{image_path.stem}.webp"


def create_image_thumbnail(
    image_path: Path,
    *,
    logger: AppLogger | None = None,
) -> str:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        if logger is not None:
            logger.log("缩略图生成跳过：当前运行环境缺少 Pillow。")
        return ""

    try:
        source = Path(image_path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            return ""
        target = thumbnail_path_for_image(source)
        ensure_dir(target.parent)
        if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
            return str(target)
        with Image.open(source) as image:
            normalized = ImageOps.exif_transpose(image)
            normalized.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE))
            if normalized.mode not in {"RGB", "RGBA"}:
                normalized = normalized.convert("RGBA" if "A" in normalized.getbands() else "RGB")
            if normalized.mode == "RGBA":
                background = Image.new("RGB", normalized.size, (255, 255, 255))
                background.paste(normalized, mask=normalized.getchannel("A"))
                normalized = background
            normalized.save(target, format="WEBP", quality=THUMBNAIL_QUALITY, method=4)
        return str(target)
    except Exception as exc:
        if logger is not None:
            logger.log(f"缩略图生成失败：{image_path} -> {exc}")
        return ""


def download_bytes(
    url: str,
    *,
    connect_timeout_seconds: int,
    read_timeout_seconds: int,
    retry_count: int,
    logger: AppLogger,
    label: str,
    use_system_proxy: bool = False,
) -> HttpResponseData:
    validate_download_url(url)
    return request_bytes_with_retries(
        "GET",
        url,
        headers={
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
        },
        body=None,
        connect_timeout_seconds=connect_timeout_seconds,
        read_timeout_seconds=read_timeout_seconds,
        retry_count=retry_count,
        label=label,
        logger=logger,
        use_system_proxy=use_system_proxy,
    )


def normalize_image_model(value: Any) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return DEFAULT_IMAGE_MODEL
    normalized = cleaned.lower()
    normalized = LEGACY_IMAGE_MODEL_ALIASES.get(normalized, normalized)
    if normalized in SUPPORTED_IMAGE_MODELS:
        return normalized
    raise AppError(f"不支持的生图模型：{cleaned}")


def image_model_from_settings(settings: Settings) -> str:
    return normalize_image_model(settings.image_model)


def is_gpt_image_model(model_name: str) -> bool:
    return model_name.lower().startswith("gpt-image")


def is_nano_banana_model(model_name: str) -> bool:
    return normalize_image_model(model_name) in NANO_BANANA_MODELS


def image_model_choices() -> list[dict[str, str]]:
    return [
        {"value": IMAGE_MODEL_GPT_IMAGE_2, "label": "gpt-image-2"},
        {
            "value": IMAGE_MODEL_NANO_BANANA_2,
            "label": "gemini-3.1-flash-image-preview（原 banana2）",
        },
        {
            "value": IMAGE_MODEL_NANO_BANANA_PRO,
            "label": "gemini-3-pro-image-preview（原 banana-pro）",
        },
    ]


def supported_nano_banana_aspect_ratios(model_name: str) -> set[str]:
    model = normalize_image_model(model_name)
    if model == IMAGE_MODEL_NANO_BANANA_2:
        return NANO_BANANA_COMMON_ASPECT_RATIOS | NANO_BANANA_2_ONLY_ASPECT_RATIOS
    if model == IMAGE_MODEL_NANO_BANANA_PRO:
        return set(NANO_BANANA_COMMON_ASPECT_RATIOS)
    return set()


def configured_image_model_id(settings: Settings, field_name: str, fallback: str) -> str:
    return str(getattr(settings, field_name, "") or "").strip() or fallback


def gpt_image_api_base(settings: Settings) -> str:
    return str(
        settings.gpt_image_api_base or settings.image_api_base or DEFAULT_API_BASE
    ).rstrip("/")


def gpt_image_request_api_base(settings: Settings, output_resolution: Any) -> str:
    resolution = normalize_output_resolution(output_resolution)
    if resolution == "1k":
        return str(
            settings.gpt_image_1k_api_base
            or settings.gpt_image_api_base
            or settings.image_api_base
            or DEFAULT_API_BASE
        ).rstrip("/")
    return gpt_image_api_base(settings)


def gemini_image_api_base(settings: Settings) -> str:
    return str(
        settings.gemini_image_api_base or settings.image_api_base or DEFAULT_API_BASE
    ).rstrip("/")


def has_image_api_key_for_model(settings: Settings, image_model: str) -> bool:
    model = normalize_image_model(image_model)
    if is_nano_banana_model(model):
        return bool(resolve_secret_value(settings.gemini_image_api_key))
    return bool(
        resolve_secret_value(settings.gpt_image_api_key)
        or resolve_secret_value(settings.gpt_image_1k_api_key)
        or resolve_secret_value(settings.image_api_key)
        or resolve_secret_value(settings.image_1k_api_key)
    )


def gemini_image_size(output_resolution: str) -> str:
    return normalize_output_resolution(output_resolution).upper()


def gemini_image_endpoint(settings: Settings, image_model: str) -> str:
    model = normalize_image_model(image_model)
    if not is_nano_banana_model(model):
        raise AppError(f"{model} 不是 Gemini 官方格式生图模型。")
    return f"{gemini_image_api_base(settings)}/v1beta/models/{model}:generateContent"


def resolve_effective_image_model(
    *,
    settings: Settings,
    image_model: str,
    output_resolution: str,
    output_aspect_ratio: str,
) -> str:
    model = normalize_image_model(image_model)
    resolution = normalize_output_resolution(output_resolution)
    if not is_nano_banana_model(model):
        if resolution == "1k":
            return configured_image_model_id(
                settings,
                "image_model_gpt_image_2_1k",
                configured_image_model_id(
                    settings,
                    "image_model_gpt_image_2",
                    DEFAULT_IMAGE_MODEL_GPT_IMAGE_2_ID,
                ),
            )
        return configured_image_model_id(
            settings,
            "image_model_gpt_image_2",
            DEFAULT_IMAGE_MODEL_GPT_IMAGE_2_ID,
        )
    aspect_ratio = normalize_output_aspect_ratio(output_aspect_ratio)
    if resolution == "auto":
        raise AppError("Gemini 官方格式生图必须选择 1K、2K 或 4K 分辨率。")
    if aspect_ratio == "auto":
        raise AppError("Gemini 官方格式生图必须选择具体比例，不能使用 auto。")
    supported_ratios = supported_nano_banana_aspect_ratios(model)
    if aspect_ratio not in supported_ratios:
        raise AppError(f"{model} 不支持比例 {aspect_ratio}。请按比例下拉框标注选择。")
    return model


def build_image_request_fields(
    *,
    prompt_text: str,
    settings: Settings,
    image_model: str | None = None,
    request_config: dict[str, str],
    include_count: int = 1,
) -> tuple[dict[str, Any], str]:
    logical_model = normalize_image_model(image_model or image_model_from_settings(settings))
    effective_model = resolve_effective_image_model(
        settings=settings,
        image_model=logical_model,
        output_resolution=request_config["output_resolution"],
        output_aspect_ratio=request_config["output_aspect_ratio"],
    )
    fields: dict[str, Any] = {
        "prompt": prompt_text,
        "model": effective_model,
    }
    if is_nano_banana_model(logical_model):
        fields["aspect_ratio"] = request_config["output_aspect_ratio"]
    else:
        if include_count > 1:
            fields["n"] = include_count
        if request_config["size"]:
            fields["size"] = request_config["size"]
    return fields, effective_model


def build_gemini_image_payload(
    *,
    prompt_text: str,
    input_images: list[Path],
    request_config: dict[str, str],
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    for image_path in input_images:
        parts.append(
            {
                "inlineData": {
                    "data": base64.b64encode(image_path.read_bytes()).decode("ascii"),
                    "mimeType": guess_mime_type(image_path),
                }
            }
        )
    parts.append({"text": prompt_text})
    return {
        "contents": [
            {
                "role": "user",
                "parts": parts,
            }
        ],
        "generationConfig": {
            "imageConfig": {
                "aspectRatio": request_config["output_aspect_ratio"],
                "imageSize": gemini_image_size(request_config["output_resolution"]),
            },
            "responseModalities": ["IMAGE"],
        },
    }


def redact_gemini_image_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = json.loads(json.dumps(payload))
    for content in redacted.get("contents", []):
        for part in content.get("parts", []):
            inline_data = part.get("inlineData")
            if isinstance(inline_data, dict) and "data" in inline_data:
                data = str(inline_data.get("data") or "")
                inline_data["data"] = f"<base64 image redacted, {len(data)} chars>"
    return redacted


def normalize_output_preset(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return DEFAULT_ASPECT_RATIO
    normalized = LEGACY_OUTPUT_PRESET_ALIASES.get(cleaned, cleaned)
    return REMOVED_OUTPUT_PRESET_FALLBACKS.get(normalized, normalized)


def normalize_output_resolution(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return DEFAULT_OUTPUT_RESOLUTION
    if cleaned in OUTPUT_RESOLUTION_OPTIONS:
        return cleaned
    raise AppError(f"不支持的分辨率档位：{cleaned}")


def normalize_output_aspect_ratio(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return DEFAULT_OUTPUT_ASPECT_RATIO
    if cleaned in OUTPUT_ASPECT_RATIO_OPTIONS:
        return cleaned
    legacy_value = normalize_output_preset(cleaned)
    legacy_pair = LEGACY_OUTPUT_SELECTION_ALIASES.get(legacy_value)
    if legacy_pair:
        return legacy_pair[1]
    raise AppError(f"不支持的画幅比例：{cleaned}")


def parse_output_selection(
    *,
    output_resolution: Any = None,
    output_aspect_ratio: Any = None,
    legacy_output: Any = None,
) -> tuple[str, str]:
    resolution_value = str(output_resolution or "").strip()
    aspect_ratio_value = str(output_aspect_ratio or "").strip()
    if resolution_value or aspect_ratio_value:
        return (
            normalize_output_resolution(resolution_value),
            normalize_output_aspect_ratio(aspect_ratio_value),
        )
    legacy_value = normalize_output_preset(str(legacy_output or ""))
    return LEGACY_OUTPUT_SELECTION_ALIASES.get(
        legacy_value,
        (DEFAULT_OUTPUT_RESOLUTION, DEFAULT_OUTPUT_ASPECT_RATIO),
    )


def output_selection_to_legacy_value(
    output_resolution: str,
    output_aspect_ratio: str,
) -> str:
    normalized_resolution = normalize_output_resolution(output_resolution)
    normalized_aspect_ratio = normalize_output_aspect_ratio(output_aspect_ratio)
    for legacy_value, pair in LEGACY_OUTPUT_SELECTION_ALIASES.items():
        if pair == (normalized_resolution, normalized_aspect_ratio):
            return legacy_value
    if normalized_resolution == "auto" or normalized_aspect_ratio == "auto":
        return "auto"
    return normalized_aspect_ratio


def output_preset_label(value: str) -> str:
    normalized = normalize_output_preset(value)
    return OUTPUT_PRESET_LABELS.get(normalized, normalized)


def output_preset_choices() -> list[dict[str, str]]:
    return [
        {"value": item, "label": OUTPUT_PRESET_LABELS.get(item, item)}
        for item in SUPPORTED_OUTPUT_PRESETS
    ]


def output_resolution_choices() -> list[dict[str, str]]:
    return [
        {
            "value": value,
            "label": OUTPUT_RESOLUTION_LABELS.get(value, value),
        }
        for value in OUTPUT_RESOLUTION_OPTIONS
    ]


def output_aspect_ratio_choices() -> list[dict[str, str]]:
    return [
        {"value": value, "label": OUTPUT_ASPECT_RATIO_LABELS.get(value, value)}
        for value in OUTPUT_ASPECT_RATIO_OPTIONS
    ]


def output_selection_label(
    output_resolution: Any,
    output_aspect_ratio: Any,
    resolved_size: str | None = None,
) -> str:
    resolution, aspect_ratio = parse_output_selection(
        output_resolution=output_resolution,
        output_aspect_ratio=output_aspect_ratio,
    )
    if resolution == "auto" or aspect_ratio == "auto":
        return "auto"
    resolution_label = OUTPUT_RESOLUTION_LABELS.get(resolution, resolution)
    aspect_ratio_label = OUTPUT_ASPECT_RATIO_LABELS.get(aspect_ratio, aspect_ratio)
    if resolved_size and resolved_size != "auto":
        return f"{resolution_label} / {aspect_ratio_label} / {resolved_size}"
    return f"{resolution_label} / {aspect_ratio_label}"


def parse_aspect_ratio_pair(value: str) -> tuple[int, int]:
    normalized = normalize_output_aspect_ratio(value)
    if normalized == "auto":
        raise AppError("auto 比例不能直接换算成固定尺寸。")
    left, right = normalized.split(":", 1)
    width = int(left)
    height = int(right)
    if width <= 0 or height <= 0:
        raise AppError(f"无效的画幅比例：{value}")
    reduced = math.gcd(width, height)
    return width // reduced, height // reduced


def resolve_output_size(
    output_resolution: Any,
    output_aspect_ratio: Any,
) -> str:
    resolution = normalize_output_resolution(output_resolution)
    aspect_ratio = normalize_output_aspect_ratio(output_aspect_ratio)
    if resolution == "auto" or aspect_ratio == "auto":
        return "auto"

    override_size = OUTPUT_RESOLUTION_SIZE_OVERRIDES.get(resolution, {}).get(aspect_ratio)
    if override_size:
        return override_size

    width_ratio, height_ratio = parse_aspect_ratio_pair(aspect_ratio)
    scale_multiple = math.lcm(
        IMAGE_SIZE_MULTIPLE // math.gcd(IMAGE_SIZE_MULTIPLE, width_ratio),
        IMAGE_SIZE_MULTIPLE // math.gcd(IMAGE_SIZE_MULTIPLE, height_ratio),
    )
    ratio_pixels = width_ratio * height_ratio
    longest_ratio_edge = max(width_ratio, height_ratio)
    min_scale = math.sqrt(IMAGE_SIZE_MIN_PIXELS / ratio_pixels)
    max_scale = min(
        math.sqrt(IMAGE_SIZE_MAX_PIXELS / ratio_pixels),
        IMAGE_SIZE_MAX_EDGE / longest_ratio_edge,
    )
    min_scale_aligned = math.ceil(min_scale / scale_multiple) * scale_multiple
    max_scale_aligned = math.floor(max_scale / scale_multiple) * scale_multiple
    if min_scale_aligned > max_scale_aligned:
        raise AppError(f"比例 {aspect_ratio} 无法换算成合法尺寸。")

    target_edge = OUTPUT_RESOLUTION_LONG_EDGE[resolution]
    target_edge_mode = OUTPUT_RESOLUTION_TARGET_EDGE_MODE.get(resolution, "long")
    target_ratio_edge = (
        min(width_ratio, height_ratio)
        if target_edge_mode == "short"
        else longest_ratio_edge
    )
    target_scale = target_edge / target_ratio_edge
    target_scale_aligned = round(target_scale / scale_multiple) * scale_multiple
    if target_scale_aligned < min_scale_aligned:
        target_scale_aligned = min_scale_aligned
    if target_scale_aligned > max_scale_aligned:
        target_scale_aligned = max_scale_aligned

    width = width_ratio * target_scale_aligned
    height = height_ratio * target_scale_aligned
    return f"{width}x{height}"


def resolve_image_request_config(
    *,
    output_resolution: Any,
    output_aspect_ratio: Any,
    settings: Settings,
    image_model: str | None = None,
    input_images: list[Path] | None = None,
    logger: Any | None = None,
) -> dict[str, str]:
    resolution, aspect_ratio = parse_output_selection(
        output_resolution=output_resolution,
        output_aspect_ratio=output_aspect_ratio,
    )
    selected_model = normalize_image_model(image_model or settings.image_model)
    if not is_nano_banana_model(selected_model):
        if not input_images and aspect_ratio == "auto":
            if logger is not None:
                logger.log(
                    "GPT image2 文生图输出规格：无输入图且比例 auto，"
                    "按 1K 路线请求并让模型自动决定 size。"
                )
            return {
                "output_resolution": "1k",
                "output_aspect_ratio": "auto",
                "size": "auto",
                "label": f"{OUTPUT_RESOLUTION_LABELS['1k']} / auto",
            }
        if resolution == "auto" and aspect_ratio != "auto":
            resolution = "1k"
            size = resolve_output_size(resolution, aspect_ratio)
            if logger is not None:
                logger.log(
                    "GPT image2 输出规格：分辨率 auto + 固定比例，"
                    f"按 1K 路线生成 {aspect_ratio} / {size}。"
                )
            return {
                "output_resolution": resolution,
                "output_aspect_ratio": aspect_ratio,
                "size": size,
                "label": output_selection_label(resolution, aspect_ratio, size),
            }
        if resolution == "4k" and aspect_ratio == "auto" and input_images:
            dims = image_file_dimensions(input_images[0], logger=logger)
            if dims:
                width, height = dims
                if (
                    image_size_resolution_bucket(width, height) == "4k"
                    and is_direct_gpt_image_size(width, height)
                ):
                    inferred_ratio = reduced_ratio_label(width, height)
                    size = f"{width}x{height}"
                    if logger is not None:
                        logger.log(
                            "GPT image2 4K auto 输出尺寸："
                            f"使用第一张输入图原始尺寸 {size}，比例 {inferred_ratio}。"
                        )
                    return {
                        "output_resolution": "4k",
                        "output_aspect_ratio": aspect_ratio,
                        "size": size,
                        "label": f"{OUTPUT_RESOLUTION_LABELS['4k']} / auto / {size}",
                        "inferred_aspect_ratio": inferred_ratio,
                    }
                inferred_ratio = closest_output_aspect_ratio_for_size(width, height)
                size = resolve_output_size("4k", inferred_ratio)
                if logger is not None:
                    logger.log(
                        "GPT image2 4K auto 输出尺寸："
                        f"第一张输入图 {width}x{height} 不是 4K 或不适合直传，"
                        f"映射为 4K / {inferred_ratio} / {size}。"
                    )
                return {
                    "output_resolution": "4k",
                    "output_aspect_ratio": inferred_ratio,
                    "size": size,
                    "label": output_selection_label("4k", inferred_ratio, size),
                }

    size = resolve_output_size(resolution, aspect_ratio)
    return {
        "output_resolution": resolution,
        "output_aspect_ratio": aspect_ratio,
        "size": size,
        "label": output_selection_label(resolution, aspect_ratio, size),
    }


def resolve_image_api_selection(
    settings: Settings,
    output_resolution: Any,
    image_model: str | None = None,
) -> dict[str, str]:
    resolution = normalize_output_resolution(output_resolution)
    selected_model = normalize_image_model(image_model or settings.image_model)
    if is_nano_banana_model(selected_model):
        gemini_key = resolve_secret_value(settings.gemini_image_api_key)
        if gemini_key:
            return {"api_key": gemini_key, "key_slot": "gemini"}
        raise AppError("请先在设置页填写有效的 Gemini 生图 API Key。")
    if resolution == "1k":
        key_1k = (
            resolve_secret_value(settings.gpt_image_1k_api_key)
            or resolve_secret_value(settings.image_1k_api_key)
        )
        if key_1k:
            return {"api_key": key_1k, "key_slot": "gpt-1k"}
        raise AppError("请先在设置页填写有效的 gpt-image-2 1K API Key。")
    default_key = (
        resolve_secret_value(settings.gpt_image_api_key)
        or resolve_secret_value(settings.image_api_key)
    )
    if default_key:
        return {"api_key": default_key, "key_slot": "gpt-2k4k"}
    raise AppError("请先在设置页填写有效的 gpt-image-2 2K/4K API Key。")


def resolve_image_size_and_ratio(
    image_model: str,
    output_preset: str,
) -> tuple[str | None, str | None]:
    resolution, aspect_ratio = parse_output_selection(legacy_output=output_preset)
    resolved_size = resolve_output_size(resolution, aspect_ratio)
    if resolved_size == "auto":
        return "auto", None
    if is_gpt_image_model(image_model):
        return resolved_size, None
    return resolved_size, aspect_ratio if aspect_ratio != "auto" else None


def create_run_paths(context: AppContext, project_name: str) -> dict[str, Path | str]:
    now = datetime.now()
    base_run_id = now.strftime("%Y%m%d-%H%M%S-%f")[:-3]
    project_slug = "image"
    project_dir = context.data_dir / project_slug
    ensure_dir(project_dir)
    for attempt in range(1000):
        run_id = base_run_id if attempt == 0 else f"{base_run_id}-{attempt:03d}"
        run_dir = project_dir / run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        json_dir = run_dir / "json"
        images_dir = run_dir / "images"
        for path in (json_dir, images_dir):
            ensure_dir(path)
        return {
            "run_id": run_id,
            "project_slug": project_slug,
            "run_dir": run_dir,
            "json_dir": json_dir,
            "images_dir": images_dir,
        }
    raise AppError("无法创建唯一的任务输出目录，请稍后重试。")


def cleanup_failed_run_dir(context: AppContext, run_dir: Path) -> None:
    try:
        resolved_run_dir = run_dir.expanduser().resolve()
        resolved_data_dir = context.data_dir.expanduser().resolve()
        resolved_run_dir.relative_to(resolved_data_dir)
    except Exception:
        return
    shutil.rmtree(resolved_run_dir, ignore_errors=True)


def preserve_failed_run_diagnostics(
    context: AppContext,
    run_dir: Path,
    *,
    label: str,
) -> Path | None:
    try:
        resolved_run_dir = run_dir.expanduser().resolve()
        resolved_data_dir = context.data_dir.expanduser().resolve()
        resolved_run_dir.relative_to(resolved_data_dir)
    except Exception:
        return None
    if not resolved_run_dir.exists() or not resolved_run_dir.is_dir():
        return None
    target_root = context.logs_dir / "failed-runs" / sanitize_project_name(label)
    target = target_root / resolved_run_dir.name
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    try:
        shutil.copytree(resolved_run_dir, target)
    except Exception:
        return None
    return target


def build_image_request_idempotency_key(run_id: str, scope: str, item_key: str) -> str:
    return f"imag-replicate2-{run_id}-{scope}-{item_key}-{uuid.uuid4().hex}"


def parse_reference_urls(value: Any) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    return [
        item.strip()
        for item in re.split(r"[\s,，;；]+", raw)
        if item.strip()
    ]


def source_spec_items(source: SourceSpec) -> list[SourceSpec]:
    items: list[SourceSpec] = []
    for file_path in source.file_paths:
        cleaned = str(file_path or "").strip()
        if cleaned:
            items.append(SourceSpec(file_path=cleaned))
    for url in source.urls:
        cleaned = str(url or "").strip()
        if cleaned:
            items.append(SourceSpec(url=cleaned))
    if not items:
        if source.file_path.strip():
            items.append(SourceSpec(file_path=source.file_path.strip()))
        if source.url.strip():
            items.append(SourceSpec(url=source.url.strip()))
    return items


def source_spec_count(source: SourceSpec) -> int:
    return len(source_spec_items(source))


def resolve_reference_source(
    source_name: str,
    source: SourceSpec,
    *,
    target_dir: Path,
    settings: Settings,
    logger: AppLogger,
) -> tuple[Path, dict[str, Any]]:
    file_path = source.file_path.strip()
    url = source.url.strip()
    if file_path:
        resolved = Path(file_path).expanduser().resolve()
        if not resolved.exists() or not resolved.is_file():
            raise AppError(f"{source_name} 本地文件不存在：{resolved}")
        suffix = resolved.suffix or ".png"
        copied = target_dir / f"{source_name}{suffix.lower()}"
        shutil.copy2(resolved, copied)
        metadata = {
            "kind": "file",
            "source": str(resolved),
            "saved_path": str(copied),
        }
        logger.log(f"{source_name}: 已复制本地图片到 {copied}")
        return copied, metadata

    if url:
        response = download_bytes(
            url,
            connect_timeout_seconds=settings.image_connect_timeout_seconds,
            read_timeout_seconds=settings.download_read_timeout_seconds,
            retry_count=settings.image_retry_count,
            logger=logger,
            label=f"{source_name} source download",
            use_system_proxy=settings.use_system_proxy,
        )
        extension = (
            extension_from_url(url)
            or extension_from_content_type(response.headers.get("Content-Type"))
            or extension_from_bytes(response.body)
        )
        saved = target_dir / f"{source_name}{extension}"
        saved.write_bytes(response.body)
        metadata = {
            "kind": "url",
            "source": url,
            "saved_path": str(saved),
            "content_type": response.headers.get("Content-Type", ""),
        }
        logger.log(f"{source_name}: 已下载远程图片到 {saved}")
        return saved, metadata

    raise AppError(f"{source_name} 需要提供本地文件或图片链接。")


def resolve_reference_sources(
    source_name: str,
    source: SourceSpec,
    *,
    target_dir: Path,
    settings: Settings,
    logger: AppLogger,
    max_count: int,
) -> tuple[list[Path], list[dict[str, Any]]]:
    items = source_spec_items(source)
    if not items:
        raise AppError(f"{source_name} 至少需要提供 1 张参考图。")
    if len(items) > max_count:
        raise AppError(f"{source_name} 最多支持 {max_count} 张参考图。")

    resolved_paths: list[Path] = []
    metadata: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        path, item_meta = resolve_reference_source(
            f"{source_name}-{index:02d}",
            item,
            target_dir=target_dir,
            settings=settings,
            logger=logger,
        )
        item_meta["index"] = index
        item_meta["group"] = source_name
        resolved_paths.append(path)
        metadata.append(item_meta)
    return resolved_paths, metadata


def generate_prompts(
    settings: Settings,
    *,
    style_images: list[Path],
    product_images: list[Path],
    prompt_count: int,
    user_prompt: str,
    run_dir: Path,
    json_dir: Path,
    logger: AppLogger,
) -> tuple[list[str], Any]:
    payload = chat_payload(
        settings,
        style_images=style_images,
        product_images=product_images,
        prompt_count=prompt_count,
        user_prompt=user_prompt,
    )
    response_json = request_json(
        f"{settings.llm_api_base}/v1/chat/completions",
        payload,
        api_key=settings.llm_api_key,
        idempotency_key=None,
        connect_timeout_seconds=settings.llm_connect_timeout_seconds,
        read_timeout_seconds=settings.chat_read_timeout_seconds,
        retry_count=settings.llm_retry_count,
        logger=logger,
        label="prompt generation",
        request_log_path=json_dir / "prompt.request.json",
        response_log_path=json_dir / "prompt.response.json",
        use_system_proxy=settings.use_system_proxy,
    )
    prompts = extract_numbered_prompts(extract_message_text(response_json), prompt_count)
    prompt_path = run_dir / "prompts.txt"
    prompt_path.write_text(format_prompt_lines(prompts), encoding="utf-8")
    logger.log(f"提示词已保存到 {prompt_path}")
    return prompts, response_json


def generate_style_replicate2_prompts(
    settings: Settings,
    *,
    reference_images: list[Path],
    prompt_count: int,
    user_prompt: str,
    run_dir: Path,
    json_dir: Path,
    logger: AppLogger,
) -> tuple[list[str], Any]:
    payload = style_replicate2_chat_payload(
        settings,
        reference_images=reference_images,
        prompt_count=prompt_count,
        user_prompt=user_prompt,
    )
    response_json = request_json(
        f"{settings.llm_api_base}/v1/chat/completions",
        payload,
        api_key=settings.llm_api_key,
        idempotency_key=None,
        connect_timeout_seconds=settings.llm_connect_timeout_seconds,
        read_timeout_seconds=settings.chat_read_timeout_seconds,
        retry_count=settings.llm_retry_count,
        logger=logger,
        label="style replicate 2 prompt generation",
        request_log_path=json_dir / "prompt.request.json",
        response_log_path=json_dir / "prompt.response.json",
        use_system_proxy=settings.use_system_proxy,
    )
    prompts = extract_numbered_prompts(extract_message_text(response_json), prompt_count)
    prompt_path = run_dir / "prompts.txt"
    prompt_path.write_text(format_prompt_lines(prompts), encoding="utf-8")
    logger.log(f"复刻风格图片2提示词已保存到 {prompt_path}")
    return prompts, response_json


def generate_color_analysis_text(
    settings: Settings,
    *,
    tone_image: Path,
    run_dir: Path,
    json_dir: Path,
    logger: AppLogger,
) -> str:
    api_key = resolve_secret_value(settings.color_match_api_key)
    if not api_key:
        raise AppError("请先在设置页填写有效的追色大模型 API Key。")
    payload = color_analysis_chat_payload(settings, tone_image=tone_image)
    response_json = request_json(
        f"{settings.color_match_api_base}/v1/chat/completions",
        payload,
        api_key=api_key,
        idempotency_key=None,
        connect_timeout_seconds=settings.llm_connect_timeout_seconds,
        read_timeout_seconds=settings.chat_read_timeout_seconds,
        retry_count=settings.llm_retry_count,
        logger=logger,
        label="color analysis",
        request_log_path=json_dir / "color-analysis.request.json",
        response_log_path=json_dir / "color-analysis.response.json",
        use_system_proxy=settings.use_system_proxy,
    )
    analysis_text = extract_message_text(response_json)
    analysis_path = run_dir / "color-analysis.md"
    analysis_path.write_text(analysis_text + "\n", encoding="utf-8")
    logger.log(f"色彩分析已保存到 {analysis_path}")
    return analysis_text


def normalize_image_agent_plan(
    raw_plan: dict[str, Any],
    *,
    user_prompt: str = "",
) -> dict[str, Any]:
    raw_needs_image = raw_plan.get("needs_image")
    response_text = str(
        raw_plan.get("response_text")
        or raw_plan.get("answer")
        or raw_plan.get("assistant_response")
        or ""
    ).strip()
    if isinstance(raw_needs_image, bool):
        needs_image = raw_needs_image
    else:
        raw_intent = str(
            raw_plan.get("intent") or raw_plan.get("mode") or raw_plan.get("task_type") or ""
        ).strip().lower()
        if raw_intent in {"chat", "text", "answer", "text_only", "no_image"}:
            needs_image = False
        elif raw_intent in {"image", "generate", "edit", "image_generation"}:
            needs_image = True
        else:
            needs_image = not bool(response_text)
    raw_count = raw_plan.get("image_count")
    if not needs_image:
        image_count = 0
    elif raw_count in (None, ""):
        deliverable_count = raw_plan.get("deliverables")
        if isinstance(deliverable_count, list) and deliverable_count:
            raw_count = len(deliverable_count)
        else:
            raw_count = infer_agent_image_count_from_text(user_prompt)
        image_count = bounded_agent_image_count(raw_count)
    else:
        image_count = bounded_agent_image_count(raw_count)
    steps = raw_plan.get("steps")
    if not isinstance(steps, list):
        steps = []
    normalized_steps = [
        {
            "title": str(item.get("title", "")).strip() if isinstance(item, dict) else "",
            "description": str(item.get("description", "")).strip()
            if isinstance(item, dict)
            else str(item).strip(),
        }
        for item in steps
        if item
    ]
    deliverables = raw_plan.get("deliverables")
    if not isinstance(deliverables, list):
        deliverables = []
    normalized_deliverables: list[dict[str, Any]] = []
    if needs_image:
        for index, item in enumerate(deliverables[:image_count], start=1):
            if isinstance(item, dict):
                title = str(item.get("title") or f"图片 {index}").strip()
                description = str(item.get("description") or "").strip()
            else:
                title = f"图片 {index}"
                description = str(item).strip()
            normalized_deliverables.append(
                {"index": index, "title": title or f"图片 {index}", "description": description}
            )
        while len(normalized_deliverables) < image_count:
            index = len(normalized_deliverables) + 1
            normalized_deliverables.append(
                {"index": index, "title": f"图片 {index}", "description": "根据用户需求生成一张图片。"}
            )

    notes = raw_plan.get("notes")
    if not isinstance(notes, list):
        notes = [notes] if notes else []
    if not needs_image and not response_text:
        response_text = str(raw_plan.get("summary") or "").strip()
    return {
        "summary": str(raw_plan.get("summary") or "").strip(),
        "needs_image": needs_image,
        "response_text": response_text,
        "image_count": image_count,
        "output_resolution": str(raw_plan.get("output_resolution") or "1k").strip().lower(),
        "output_aspect_ratio": str(raw_plan.get("output_aspect_ratio") or "1:1").strip().lower(),
        "reference_usage": str(raw_plan.get("reference_usage") or "").strip(),
        "steps": normalized_steps,
        "deliverables": normalized_deliverables,
        "notes": [str(item).strip() for item in notes if str(item).strip()],
    }


AGENT_GENERATE_TOOL_NAMES = {
    "generate_image_by_selected_model",
    "generate_image_by_gpt_image_1_jaaz",
}


def agent_prompt_text_from_item(item: dict[str, Any]) -> str:
    for key in (
        "prompt",
        "image_prompt",
        "generation_prompt",
        "positive_prompt",
        "description",
    ):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalize_image_agent_prompt_items(
    raw_prompts: Any,
    *,
    image_count: int,
) -> list[dict[str, Any]]:
    prompt_items: list[dict[str, Any]] = []
    if isinstance(raw_prompts, str):
        raw_prompts = extract_numbered_prompts(raw_prompts, image_count)
    if not isinstance(raw_prompts, list):
        return []
    for index, item in enumerate(raw_prompts[:image_count], start=1):
        if isinstance(item, str):
            prompt_text = item.strip()
            raw_item: dict[str, Any] = {}
        elif isinstance(item, dict):
            prompt_text = agent_prompt_text_from_item(item)
            raw_item = item
        else:
            continue
        if not prompt_text:
            continue
        aspect_ratio = str(
            raw_item.get("aspect_ratio") or raw_item.get("output_aspect_ratio") or ""
        ).strip()
        output_resolution = str(
            raw_item.get("output_resolution") or raw_item.get("resolution") or ""
        ).strip()
        normalized_item = {
            "index": int(raw_item.get("index") or index),
            "title": str(raw_item.get("title") or f"图片 {index}").strip(),
            "prompt": prompt_text,
        }
        if output_resolution:
            normalized_item["output_resolution"] = output_resolution.lower()
        if aspect_ratio:
            normalized_item["output_aspect_ratio"] = aspect_ratio.lower()
        input_images = raw_item.get("input_images")
        if isinstance(input_images, list):
            normalized_item["input_images"] = [
                str(value).strip() for value in input_images if str(value).strip()
            ]
        prompt_items.append(normalized_item)
    return prompt_items


def first_agent_prompt_list(raw_design: dict[str, Any]) -> Any:
    for key in ("prompts", "images", "image_tasks", "tasks", "deliverables"):
        value = raw_design.get(key)
        if isinstance(value, list) and value:
            return value
    return raw_design.get("prompts")


def normalize_image_agent_design(
    raw_design: dict[str, Any],
    *,
    image_count: int,
) -> tuple[str, list[dict[str, Any]]]:
    design_strategy = str(
        raw_design.get("design_strategy")
        or raw_design.get("design_strategy_doc")
        or raw_design.get("strategy")
        or raw_design.get("summary")
        or ""
    ).strip()
    prompt_items = normalize_image_agent_prompt_items(
        first_agent_prompt_list(raw_design),
        image_count=image_count,
    )
    if len(prompt_items) != image_count:
        raise AppError(
            f"Agent 需要返回 {image_count} 条生图提示词，但实际解析到 {len(prompt_items)} 条。"
        )
    return design_strategy, prompt_items


def extract_image_agent_tool_prompt_items(
    response_json: Any,
    *,
    image_count: int,
) -> list[dict[str, Any]]:
    raw_items: list[dict[str, Any]] = []
    for call in extract_llm_tool_calls(response_json):
        if call.get("name") not in AGENT_GENERATE_TOOL_NAMES:
            continue
        arguments = call.get("arguments")
        if isinstance(arguments, dict):
            nested_items = first_agent_prompt_list(arguments)
            if isinstance(nested_items, list) and nested_items:
                raw_items.extend(
                    item for item in nested_items if isinstance(item, (dict, str))
                )
            else:
                raw_items.append(arguments)
    prompt_items = normalize_image_agent_prompt_items(
        raw_items,
        image_count=image_count,
    )
    if len(prompt_items) != image_count:
        return []
    return prompt_items


def normalize_image_agent_design_from_text(
    text: str,
    *,
    image_count: int,
) -> tuple[str, list[dict[str, Any]]]:
    try:
        return normalize_image_agent_design(
            parse_json_object_text(text, label="Agent 创作阶段"),
            image_count=image_count,
        )
    except AppError:
        prompts = extract_numbered_prompts(text, image_count)
        prompt_items = normalize_image_agent_prompt_items(
            prompts,
            image_count=image_count,
        )
        return "", prompt_items


def build_agent_input_image_registry(
    current_input_images: list[Path],
    context_image_refs: list[dict[str, Any]],
) -> dict[str, Path]:
    registry: dict[str, Path] = {
        f"reference_image_{index}": image_path
        for index, image_path in enumerate(current_input_images, start=1)
    }
    for ref in context_image_refs:
        ref_id = str(ref.get("id") or "").strip()
        image_path = ref.get("path")
        if ref_id and isinstance(image_path, Path):
            registry[ref_id] = image_path
    return registry


def is_referential_image_followup(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    markers = (
        "这张",
        "这个",
        "这个图",
        "这图",
        "上一张",
        "上一次",
        "刚才",
        "前面",
        "之前",
        "效果不是",
        "效果不",
        "不对",
        "不像",
        "改成",
        "调整",
        "优化",
        "继续",
        "基于",
        "参考",
        "this image",
        "this one",
        "previous image",
        "last image",
        "above image",
        "not like this",
        "fix it",
        "revise",
        "adjust",
        "based on",
    )
    return any(marker in text for marker in markers)


def select_agent_render_input_images(
    item: dict[str, Any],
    *,
    user_prompt: str,
    current_input_images: list[Path],
    context_image_refs: list[dict[str, Any]],
    input_image_registry: dict[str, Path],
) -> list[Path]:
    raw_ids = item.get("input_images")
    if isinstance(raw_ids, list) and raw_ids:
        selected: list[Path] = []
        seen_paths: set[str] = set()
        for raw_id in raw_ids:
            image_id = str(raw_id or "").strip()
            image_path = input_image_registry.get(image_id)
            if not image_path:
                continue
            resolved_key = str(image_path.resolve())
            if resolved_key in seen_paths:
                continue
            selected.append(image_path)
            seen_paths.add(resolved_key)
        if selected:
            return selected[:MAX_IMAGE_EDIT_INPUT_IMAGES]
    if current_input_images:
        return current_input_images
    if not is_referential_image_followup(user_prompt):
        return []
    return [
        ref["path"]
        for ref in select_agent_visual_context_refs(
            context_image_refs,
            max_count=MAX_IMAGE_EDIT_INPUT_IMAGES,
        )
        if isinstance(ref.get("path"), Path)
    ][:MAX_IMAGE_EDIT_INPUT_IMAGES]


def repair_image_agent_design_response(
    settings: Settings,
    *,
    user_prompt: str,
    input_images: list[Path],
    context_image_refs: list[dict[str, Any]] | None = None,
    selected_image_model: str,
    effective_image_model: str,
    request_config: dict[str, Any],
    allowed_resolutions: list[str],
    default_resolution: str | None,
    plan: dict[str, Any],
    conversation_context: str,
    invalid_text: str,
    parse_error: str,
    image_count: int,
    json_dir: Path,
    logger: AppLogger,
) -> tuple[str, list[dict[str, Any]], Any]:
    repair_prompt = textwrap.dedent(
        f"""
        The previous image creator response could not be parsed.
        Parse error: {parse_error}

        Return exactly one JSON object and no Markdown.
        Required shape:
        {{
          "design_strategy": "short practical strategy in the user's language",
          "prompts": [
            {{
              "title": "image title",
              "prompt": "detailed English image generation prompt",
              "output_resolution": "one of: {', '.join(allowed_resolutions)}",
              "aspect_ratio": "one of: {', '.join(image_agent_allowed_aspect_ratios(selected_image_model))}",
              "input_images": ["reference_image_1"]
            }}
          ]
        }}

        Rules:
        - prompts must contain exactly {image_count} items.
        - Every prompt must be detailed English and directly executable by the selected image model.
        - Use only allowed output_resolution and aspect_ratio values.
        - Preserve the backend-selected image model. Do not mention or switch models.
        - If reference images are useful, use only IDs from <input_images> or <context_image_refs>.

        Previous invalid response:
        {truncate_text(invalid_text, 12000)}
        """
    ).strip()
    base_payload = image_agent_chat_payload(
        settings,
        system_prompt="You repair malformed image-agent creator output into strict JSON.",
        user_prompt=f"{user_prompt}\n\n{repair_prompt}",
        input_images=input_images,
        context_image_refs=context_image_refs,
        selected_image_model=selected_image_model,
        effective_image_model=effective_image_model,
        output_resolution=request_config["output_resolution"],
        output_aspect_ratio=request_config["output_aspect_ratio"],
        resolved_size=request_config.get("size") or request_config.get("label") or "",
        allowed_resolutions=allowed_resolutions,
        default_resolution=default_resolution,
        max_tokens=settings.chat_max_tokens or max(2600, image_count * 520),
        conversation_context=conversation_context,
        plan=plan,
    )
    response_json = request_image_agent_llm(
        settings,
        base_payload,
        api_key=resolve_secret_value(settings.image_agent_api_key),
        connect_timeout_seconds=settings.llm_connect_timeout_seconds,
        read_timeout_seconds=settings.chat_read_timeout_seconds,
        retry_count=settings.llm_retry_count,
        logger=logger,
        label="image agent creator repair",
        request_log_path=json_dir / "agent-design.repair.request.json",
        response_log_path=json_dir / "agent-design.repair.response.json",
    )
    repaired_text = extract_message_text(response_json)
    design_strategy, prompt_items = normalize_image_agent_design_from_text(
        repaired_text,
        image_count=image_count,
    )
    return design_strategy, prompt_items, response_json


def extract_image_agent_plan_response(response_json: Any) -> dict[str, Any]:
    raw_plan = extract_first_tool_arguments(response_json, "write_plan")
    if raw_plan is not None:
        return raw_plan
    parse_errors: list[str] = []
    try:
        responses_text = extract_response_text(response_json)
    except AppError as exc:
        parse_errors.append(str(exc))
    else:
        try:
            return parse_json_object_text(responses_text, label="Agent 规划阶段")
        except AppError as exc:
            parse_errors.append(str(exc))
    try:
        chat_text = extract_message_text(response_json)
    except AppError as exc:
        parse_errors.append(str(exc))
    else:
        try:
            return parse_json_object_text(chat_text, label="Agent 规划阶段")
        except AppError as exc:
            parse_errors.append(str(exc))
    raise AppError(
        "Agent 规划阶段返回不可解析：Responses 返回里没有找到可用的 "
        "write_plan 工具调用或计划 JSON；"
        f"解析错误={'; '.join(parse_errors)}；"
        f"返回结构={format_llm_response_shape(response_json)}"
    )


def image_agent_plain_json_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    fallback = image_agent_plain_fallback_payload(payload)
    extra_instruction = (
        "\n\nTool calling appears unavailable for this request. Return exactly one "
        "JSON object and no Markdown, using the same fields as the write_plan "
        "tool arguments: summary, needs_image, response_text, image_count, "
        "output_resolution, output_aspect_ratio, reference_usage, steps, "
        "deliverables, and notes."
    )
    messages = fallback.get("messages")
    if isinstance(messages, list):
        next_messages: list[Any] = []
        inserted = False
        for message in messages:
            if not isinstance(message, dict):
                next_messages.append(message)
                continue
            next_message = dict(message)
            if not inserted and str(next_message.get("role") or "") == "system":
                next_message["content"] = str(next_message.get("content") or "") + extra_instruction
                inserted = True
            next_messages.append(next_message)
        if not inserted:
            next_messages.insert(
                0,
                {
                    "role": "system",
                    "content": "Return exactly one valid JSON object and no Markdown.",
                },
            )
        fallback["messages"] = next_messages
    return fallback


def generate_image_agent_plan(
    settings: Settings,
    *,
    user_prompt: str,
    input_images: list[Path],
    context_image_refs: list[dict[str, Any]] | None = None,
    selected_image_model: str,
    effective_image_model: str,
    request_config: dict[str, Any],
    allowed_resolutions: list[str],
    default_resolution: str | None,
    conversation_context: str,
    run_dir: Path,
    json_dir: Path,
    logger: AppLogger,
) -> tuple[dict[str, Any], Any]:
    api_key = resolve_secret_value(settings.image_agent_api_key)
    if not api_key:
        raise AppError("请先在设置页填写有效的 Agent 大模型 API Key。")
    base_payload = image_agent_chat_payload(
        settings,
        system_prompt=render_image_agent_system_prompt(
            settings.image_agent_planner_prompt,
            IMAGE_AGENT_PLANNER_PROMPT,
        ),
        user_prompt=user_prompt,
        input_images=input_images,
        context_image_refs=context_image_refs,
        selected_image_model=selected_image_model,
        effective_image_model=effective_image_model,
        output_resolution=request_config["output_resolution"],
        output_aspect_ratio=request_config["output_aspect_ratio"],
        resolved_size=request_config.get("size") or request_config.get("label") or "",
        allowed_resolutions=allowed_resolutions,
        default_resolution=default_resolution,
        max_tokens=settings.chat_max_tokens or 2400,
        conversation_context=conversation_context,
    )
    payload = image_agent_tool_payload(
        base_payload,
        tools=[
            image_agent_write_plan_tool_spec(
                allowed_resolutions=allowed_resolutions,
                allowed_aspect_ratios=image_agent_allowed_aspect_ratios(
                    selected_image_model
                ),
            )
        ],
        tool_name="write_plan",
    )
    response_json = request_image_agent_llm(
        settings,
        payload,
        api_key=api_key,
        connect_timeout_seconds=settings.llm_connect_timeout_seconds,
        read_timeout_seconds=settings.chat_read_timeout_seconds,
        retry_count=settings.llm_retry_count,
        logger=logger,
        label="image agent planner",
        request_log_path=json_dir / "agent-plan.request.json",
        response_log_path=json_dir / "agent-plan.response.json",
    )
    try:
        raw_plan = extract_image_agent_plan_response(response_json)
    except AppError as first_exc:
        logger.log(
            "Agent 规划结果不可解析，重试 write_plan："
            f"{first_exc}"
        )
        response_json = request_image_agent_llm(
            settings,
            payload,
            api_key=api_key,
            connect_timeout_seconds=settings.llm_connect_timeout_seconds,
            read_timeout_seconds=settings.chat_read_timeout_seconds,
            retry_count=settings.llm_retry_count,
            logger=logger,
            label="image agent planner retry",
            request_log_path=json_dir / "agent-plan.retry.request.json",
            response_log_path=json_dir / "agent-plan.retry.response.json",
        )
        try:
            raw_plan = extract_image_agent_plan_response(response_json)
        except AppError as retry_exc:
            logger.log(
                "Agent 规划重试仍不可解析，降级为纯 JSON："
                f"{retry_exc}"
            )
            response_json = request_image_agent_llm(
                settings,
                image_agent_plain_json_plan_payload(base_payload),
                api_key=api_key,
                connect_timeout_seconds=settings.llm_connect_timeout_seconds,
                read_timeout_seconds=settings.chat_read_timeout_seconds,
                retry_count=settings.llm_retry_count,
                logger=logger,
                label="image agent planner json fallback",
                request_log_path=json_dir / "agent-plan.json-fallback.request.json",
                response_log_path=json_dir / "agent-plan.json-fallback.response.json",
            )
            try:
                raw_plan = extract_image_agent_plan_response(response_json)
            except AppError as fallback_exc:
                logger.log(
                    "Agent 规划纯 JSON 降级仍不可解析："
                    f"{fallback_exc}"
                )
                raise
    plan = normalize_image_agent_plan(raw_plan, user_prompt=user_prompt)
    write_json(json_dir / "agent-plan.json", plan)
    (run_dir / "agent-plan.md").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.log(
        "Agent 规划完成："
        f"needs_image={plan.get('needs_image')}, image_count={plan['image_count']}"
    )
    return plan, response_json


def generate_image_agent_design(
    settings: Settings,
    *,
    user_prompt: str,
    input_images: list[Path],
    context_image_refs: list[dict[str, Any]] | None = None,
    selected_image_model: str,
    effective_image_model: str,
    request_config: dict[str, Any],
    allowed_resolutions: list[str],
    default_resolution: str | None,
    plan: dict[str, Any],
    conversation_context: str,
    run_dir: Path,
    json_dir: Path,
    logger: AppLogger,
) -> tuple[str, list[dict[str, Any]], Any]:
    image_count = bounded_agent_image_count(plan.get("image_count"))
    base_payload = image_agent_chat_payload(
        settings,
        system_prompt=render_image_agent_system_prompt(
            settings.image_agent_creator_prompt,
            IMAGE_AGENT_CREATOR_PROMPT,
        ),
        user_prompt=user_prompt,
        input_images=input_images,
        context_image_refs=context_image_refs,
        selected_image_model=selected_image_model,
        effective_image_model=effective_image_model,
        output_resolution=request_config["output_resolution"],
        output_aspect_ratio=request_config["output_aspect_ratio"],
        resolved_size=request_config.get("size") or request_config.get("label") or "",
        allowed_resolutions=allowed_resolutions,
        default_resolution=default_resolution,
        max_tokens=settings.chat_max_tokens or max(2600, image_count * 520),
        conversation_context=conversation_context,
        plan=plan,
    )
    payload = image_agent_tool_payload(
        base_payload,
        tools=[
            image_agent_generate_tool_spec(
                selected_image_model,
                allowed_resolutions=allowed_resolutions,
            )
        ],
    )
    response_json = request_image_agent_llm(
        settings,
        payload,
        api_key=resolve_secret_value(settings.image_agent_api_key),
        connect_timeout_seconds=settings.llm_connect_timeout_seconds,
        read_timeout_seconds=settings.chat_read_timeout_seconds,
        retry_count=settings.llm_retry_count,
        logger=logger,
        label="image agent creator",
        request_log_path=json_dir / "agent-design.request.json",
        response_log_path=json_dir / "agent-design.response.json",
    )
    design_strategy = extract_message_text_optional(response_json).strip()
    prompt_items = extract_image_agent_tool_prompt_items(
        response_json,
        image_count=image_count,
    )
    if not prompt_items:
        text = extract_message_text_optional(response_json)
        parse_error = ""
        if not text:
            actual_count = sum(
                1
                for call in extract_llm_tool_calls(response_json)
                if call.get("name") in AGENT_GENERATE_TOOL_NAMES
            )
            parse_error = (
                f"Agent 需要返回 {image_count} 条生图工具任务，但实际解析到 {actual_count} 条。"
            )
        else:
            try:
                parsed_strategy, prompt_items = normalize_image_agent_design_from_text(
                    text,
                    image_count=image_count,
                )
                if parsed_strategy:
                    design_strategy = parsed_strategy
            except AppError as exc:
                parse_error = str(exc)
        if parse_error:
            logger.log(f"Agent 创作结果不可解析，尝试修复：{parse_error}")
            parsed_strategy, prompt_items, response_json = repair_image_agent_design_response(
                settings,
                user_prompt=user_prompt,
                input_images=input_images,
                context_image_refs=context_image_refs,
                selected_image_model=selected_image_model,
                effective_image_model=effective_image_model,
                request_config=request_config,
                allowed_resolutions=allowed_resolutions,
                default_resolution=default_resolution,
                plan=plan,
                conversation_context=conversation_context,
                invalid_text=text,
                parse_error=parse_error,
                image_count=image_count,
                json_dir=json_dir,
                logger=logger,
            )
            if parsed_strategy:
                design_strategy = parsed_strategy
            logger.log(f"Agent 创作修复完成：prompts={len(prompt_items)}")
    if len(prompt_items) != image_count:
        raise AppError(
            f"Agent 需要返回 {image_count} 条生图提示词，但实际解析到 {len(prompt_items)} 条。"
        )
    tool_calls = extract_llm_tool_calls(response_json)
    write_json(
        json_dir / "agent-design.json",
        {
            "design_strategy": design_strategy,
            "prompts": prompt_items,
            "tool_calls": tool_calls,
        },
    )
    (run_dir / "agent-design.md").write_text(
        f"{design_strategy}\n\n{format_prompt_lines([item['prompt'] for item in prompt_items])}",
        encoding="utf-8",
    )
    logger.log(f"Agent 创作完成：prompts={len(prompt_items)}")
    return design_strategy, prompt_items, response_json


def save_render_outputs(
    response_json: Any,
    *,
    output_dir: Path,
    prompt_index: int,
    prompt_text: str,
    settings: Settings,
    logger: AppLogger,
    response_file: Path,
) -> dict[str, Any]:
    stem = f"{prompt_index:02d}"
    saved_files: list[str] = []
    image_details: list[dict[str, Any]] = []
    skipped_payload_errors: list[str] = []
    payloads = extract_render_payloads(response_json)
    if not payloads:
        logger.log(f"render {stem}: 返回里没有解析出图片 payload。")

    for offset, payload in enumerate(payloads, start=1):
        suffix = "" if len(payloads) == 1 else f"-{offset}"
        try:
            if payload["kind"] == "url":
                url_value = str(payload["value"]).strip()
                parsed_url = urllib.parse.urlparse(url_value)
                if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                    raise AppError("图片 URL 为空或格式无效。")
                raw_response = download_bytes(
                    url_value,
                    connect_timeout_seconds=settings.image_connect_timeout_seconds,
                    read_timeout_seconds=settings.download_read_timeout_seconds,
                    retry_count=settings.image_retry_count,
                    logger=logger,
                    label=f"render image download {stem}{suffix}",
                    use_system_proxy=settings.use_system_proxy,
                )
                raw_bytes = raw_response.body
                extension = (
                    extension_from_url(url_value)
                    or extension_from_content_type(raw_response.headers.get("Content-Type"))
                    or extension_from_bytes(raw_bytes)
                )
            else:
                encoded_value = str(payload["value"]).strip()
                if not encoded_value:
                    raise AppError("图片 payload 为空。")
                raw_bytes = base64.b64decode(encoded_value, validate=True)
                if not raw_bytes:
                    raise AppError("图片 payload 解码后为空。")
                extension = extension_from_bytes(raw_bytes)

            image_path = output_dir / f"{stem}{suffix}{extension}"
            image_path.write_bytes(raw_bytes)
            saved_files.append(str(image_path))
            thumbnail_path = create_image_thumbnail(image_path, logger=logger)
            detail: dict[str, Any] = {"path": str(image_path)}
            if thumbnail_path:
                detail["thumbnail_path"] = thumbnail_path
            dims = image_dimensions(raw_bytes)
            if dims:
                detail["width"] = dims[0]
                detail["height"] = dims[1]
                detail["ratio"] = reduced_ratio_label(dims[0], dims[1])
            image_details.append(detail)
            logger.log(f"render {stem}: 已保存图片 {image_path}")
        except Exception as exc:
            skipped_payload_errors.append(f"{payload.get('kind', 'unknown')}#{offset}: {exc}")
            logger.log(
                f"render {stem}: 跳过无效图片 payload {offset}/{len(payloads)} ({payload.get('kind', 'unknown')}) -> {exc}"
            )

    if not saved_files:
        if skipped_payload_errors:
            raise AppError(
                f"返回里没有保存成功的有效图片。最后一个 payload 错误：{skipped_payload_errors[-1]}"
            )
        raise AppError("返回里没有解析出有效图片。")

    if skipped_payload_errors:
        logger.log(
            f"render {stem}: 已跳过 {len(skipped_payload_errors)} 个无效 payload，成功保存 {len(saved_files)} 张图片。"
        )

    return {
        "index": prompt_index,
        "prompt": prompt_text,
        "response_file": str(response_file),
        "images": saved_files,
        "image_details": image_details,
    }


def render_product_reference_prompt(prompt_text: str, product_image_count: int) -> str:
    if product_image_count <= 1:
        return prompt_text
    return f"{PRODUCT_REFERENCE_RENDER_PROMPT_PREFIX}\n\n{prompt_text}"


def render_reference_prompt(
    prompt_text: str,
    input_image_count: int,
    *,
    reference_prompt_prefix: str = "",
) -> str:
    if reference_prompt_prefix.strip():
        return f"{reference_prompt_prefix.strip()}\n\n{prompt_text}"
    return render_product_reference_prompt(prompt_text, input_image_count)


def render_one_prompt(
    prompt_index: int,
    prompt_text: str,
    *,
    settings: Settings,
    run_id: str,
    product_images: list[Path],
    image_api_key: str,
    image_key_slot: str,
    output_resolution: str,
    output_aspect_ratio: str,
    images_per_prompt: int,
    output_dir: Path,
    json_dir: Path,
    logger: AppLogger,
    reference_prompt_prefix: str = "",
    endpoint_scope: str = "style-replicate",
    upload_gate: threading.Semaphore | None = None,
) -> dict[str, Any]:
    render_prompt_text = render_reference_prompt(
        prompt_text,
        len(product_images),
        reference_prompt_prefix=reference_prompt_prefix,
    )
    selected_image_model = image_model_from_settings(settings)
    request_config = resolve_image_request_config(
        output_resolution=output_resolution,
        output_aspect_ratio=output_aspect_ratio,
        settings=settings,
        image_model=selected_image_model,
        input_images=product_images,
        logger=logger,
    )
    effective_image_model = resolve_effective_image_model(
        settings=settings,
        image_model=selected_image_model,
        output_resolution=request_config["output_resolution"],
        output_aspect_ratio=request_config["output_aspect_ratio"],
    )

    idempotency_key = build_image_request_idempotency_key(
        run_id,
        endpoint_scope,
        f"{prompt_index:02d}",
    )
    endpoint_label = (
        f"/v1beta/models/{effective_image_model}:generateContent"
        if is_nano_banana_model(selected_image_model)
        else "/v1/images/edits"
    )
    logger.log(
        "render "
        f"{prompt_index:02d}: endpoint={endpoint_label}, model={effective_image_model}, "
        f"product_images={len(product_images)}, "
        f"resolution={request_config['output_resolution']}, "
        f"ratio={request_config['output_aspect_ratio']}, "
        f"size={request_config['size'] or gemini_image_size(request_config['output_resolution'])}, "
        f"key_slot={image_key_slot}, "
        f"idempotency_key={idempotency_key}"
    )
    request_path = json_dir / f"{prompt_index:02d}.request.json"
    response_path = json_dir / f"{prompt_index:02d}.response.json"
    with shared_render_slot():
        if is_nano_banana_model(selected_image_model):
            request_payload = build_gemini_image_payload(
                prompt_text=render_prompt_text,
                input_images=product_images,
                request_config=request_config,
            )
            response_json = request_json(
                gemini_image_endpoint(settings, effective_image_model),
                request_payload,
                api_key=image_api_key,
                idempotency_key=idempotency_key,
                connect_timeout_seconds=settings.image_connect_timeout_seconds,
                read_timeout_seconds=settings.image_read_timeout_seconds,
                retry_count=settings.image_retry_count,
                logger=logger,
                label=f"render {prompt_index:02d}",
                request_log_path=request_path,
                response_log_path=response_path,
                log_payload=redact_gemini_image_payload(request_payload),
                upload_gate=upload_gate,
                use_system_proxy=settings.use_system_proxy,
            )
        else:
            fields, _ = build_image_request_fields(
                prompt_text=render_prompt_text,
                settings=settings,
                image_model=selected_image_model,
                request_config=request_config,
                include_count=images_per_prompt,
            )
            response_json = request_multipart_json(
                f"{gpt_image_request_api_base(settings, request_config['output_resolution'])}/v1/images/edits",
                fields,
                file_parts=[("image", product_image) for product_image in product_images],
                api_key=image_api_key,
                idempotency_key=idempotency_key,
                connect_timeout_seconds=settings.image_connect_timeout_seconds,
                read_timeout_seconds=settings.image_read_timeout_seconds,
                retry_count=settings.image_retry_count,
                logger=logger,
                label=f"render {prompt_index:02d}",
                request_log_path=request_path,
                response_log_path=response_path,
                upload_gate=upload_gate,
                use_system_proxy=settings.use_system_proxy,
            )
        return save_render_outputs(
            response_json,
            output_dir=output_dir,
            prompt_index=prompt_index,
            prompt_text=render_prompt_text,
            settings=settings,
            logger=logger,
            response_file=response_path,
        )


def render_prompts(
    prompts: list[str],
    *,
    settings: Settings,
    run_id: str,
    product_images: list[Path],
    image_api_key: str,
    image_key_slot: str,
    output_resolution: str,
    output_aspect_ratio: str,
    images_per_prompt: int,
    concurrency: int,
    output_dir: Path,
    json_dir: Path,
    logger: AppLogger,
    reference_prompt_prefix: str = "",
    endpoint_scope: str = "style-replicate",
    upload_gate: threading.Semaphore | None = None,
) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                render_one_prompt,
                index,
                prompt_text,
                settings=settings,
                run_id=run_id,
                product_images=product_images,
                image_api_key=image_api_key,
                image_key_slot=image_key_slot,
                output_resolution=output_resolution,
                output_aspect_ratio=output_aspect_ratio,
                images_per_prompt=images_per_prompt,
                output_dir=output_dir,
                json_dir=json_dir,
                logger=logger,
                reference_prompt_prefix=reference_prompt_prefix,
                endpoint_scope=endpoint_scope,
                upload_gate=upload_gate,
            )
            for index, prompt_text in enumerate(prompts, start=1)
        ]
        for future in concurrent.futures.as_completed(futures):
            manifest.append(future.result())

    manifest.sort(key=lambda item: item["index"])
    write_json(json_dir / "manifest.json", manifest)
    logger.log(f"渲染完成，manifest 已保存到 {json_dir / 'manifest.json'}")
    return manifest


def copy_image_edit_inputs(
    image_paths: list[str],
    *,
    target_dir: Path,
    logger: AppLogger,
) -> tuple[list[Path], list[dict[str, Any]]]:
    ensure_dir(target_dir)
    copied_paths: list[Path] = []
    metadata: list[dict[str, Any]] = []
    for index, raw_path in enumerate(image_paths, start=1):
        source = Path(raw_path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise AppError(f"编辑输入图不存在：{source}")
        suffix = source.suffix.lower() or ".png"
        target = target_dir / f"{index:02d}{suffix}"
        shutil.copy2(source, target)
        copied_paths.append(target)
        metadata.append(
            {
                "index": index,
                "original_path": str(source),
                "saved_path": str(target),
                "name": source.name,
                "size": target.stat().st_size,
                "mime_type": guess_mime_type(target),
            }
        )
        logger.log(f"image edit input {index:02d}: 已保存输入图 {target}")
    return copied_paths, metadata


def copy_named_input_image(
    image_path: str,
    *,
    target_dir: Path,
    stem: str,
    label: str,
    logger: AppLogger,
) -> tuple[Path, dict[str, Any]]:
    ensure_dir(target_dir)
    source = Path(image_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise AppError(f"{label}不存在：{source}")
    suffix = source.suffix.lower() or ".png"
    target = target_dir / f"{stem}{suffix}"
    shutil.copy2(source, target)
    metadata = {
        "kind": "file",
        "source": str(source),
        "saved_path": str(target),
        "name": source.name,
        "size": target.stat().st_size,
        "mime_type": guess_mime_type(target),
    }
    logger.log(f"{label}: 已保存输入图 {target}")
    return target, metadata


def desaturate_image(source: Path, target: Path, *, logger: AppLogger) -> Path:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise AppError("当前运行环境缺少 Pillow，无法对静物场景图去色。") from exc

    ensure_dir(target.parent)
    with Image.open(source) as image:
        alpha = image.getchannel("A") if "A" in image.getbands() else None
        gray = ImageOps.grayscale(image.convert("RGB"))
        if alpha is not None:
            output = Image.merge("RGBA", (gray, gray, gray, alpha))
        else:
            output = gray.convert("RGB")
        output.save(target, format="PNG")
    logger.log(f"静物场景图已去色：{target}")
    return target


def render_image_edit(
    *,
    prompt_text: str,
    input_images: list[Path],
    settings: Settings,
    image_model: str | None = None,
    run_id: str,
    image_api_key: str,
    image_key_slot: str,
    output_resolution: str,
    output_aspect_ratio: str,
    images_per_prompt: int,
    output_dir: Path,
    json_dir: Path,
    logger: AppLogger,
    prompt_index: int = 1,
    request_file_stem: str = "edit",
    endpoint_scope: str | None = None,
    label: str = "image edit",
) -> dict[str, Any]:
    selected_image_model = normalize_image_model(image_model or settings.image_model)
    request_config = resolve_image_request_config(
        output_resolution=output_resolution,
        output_aspect_ratio=output_aspect_ratio,
        settings=settings,
        image_model=selected_image_model,
        input_images=input_images,
        logger=logger,
    )
    effective_image_model = resolve_effective_image_model(
        settings=settings,
        image_model=selected_image_model,
        output_resolution=request_config["output_resolution"],
        output_aspect_ratio=request_config["output_aspect_ratio"],
    )
    use_multipart_edit_endpoint = bool(input_images)

    request_path = json_dir / f"{request_file_stem}.request.json"
    response_path = json_dir / f"{request_file_stem}.response.json"
    resolved_endpoint_scope = (
        endpoint_scope or ("image-edit" if input_images else "image-generation")
    )
    idempotency_key = build_image_request_idempotency_key(
        run_id,
        resolved_endpoint_scope,
        f"{prompt_index:02d}",
    )
    with shared_render_slot():
        if is_nano_banana_model(selected_image_model):
            request_payload = build_gemini_image_payload(
                prompt_text=prompt_text,
                input_images=input_images,
                request_config=request_config,
            )
            endpoint_url = gemini_image_endpoint(settings, effective_image_model)
            logger.log(
                f"{label}: "
                f"endpoint={urllib.parse.urlparse(endpoint_url).path}, model={effective_image_model}, images={len(input_images)}, "
                f"resolution={request_config['output_resolution']}, "
                f"ratio={request_config['output_aspect_ratio']}, "
                f"image_size={gemini_image_size(request_config['output_resolution'])}, "
                f"key_slot={image_key_slot}, "
                f"idempotency_key={idempotency_key}"
            )
            response_json = request_json(
                endpoint_url,
                request_payload,
                api_key=image_api_key,
                idempotency_key=idempotency_key,
                connect_timeout_seconds=settings.image_connect_timeout_seconds,
                read_timeout_seconds=settings.image_read_timeout_seconds,
                retry_count=settings.image_retry_count,
                logger=logger,
                label=label,
                request_log_path=request_path,
                response_log_path=response_path,
                log_payload=redact_gemini_image_payload(request_payload),
                use_system_proxy=settings.use_system_proxy,
            )
        elif use_multipart_edit_endpoint:
            request_fields, _ = build_image_request_fields(
                prompt_text=prompt_text,
                settings=settings,
                image_model=selected_image_model,
                request_config=request_config,
                include_count=1,
            )
            logger.log(
                f"{label}: "
                f"endpoint=/v1/images/edits, model={effective_image_model}, images={len(input_images)}, "
                f"resolution={request_config['output_resolution']}, "
                f"ratio={request_config['output_aspect_ratio']}, "
                f"size={request_config['size']}, "
                f"key_slot={image_key_slot}, "
                f"idempotency_key={idempotency_key}"
            )
            response_json = request_multipart_json(
                f"{gpt_image_request_api_base(settings, request_config['output_resolution'])}/v1/images/edits",
                request_fields,
                file_parts=[("image", image_path) for image_path in input_images],
                api_key=image_api_key,
                idempotency_key=idempotency_key,
                connect_timeout_seconds=settings.image_connect_timeout_seconds,
                read_timeout_seconds=settings.image_read_timeout_seconds,
                retry_count=settings.image_retry_count,
                logger=logger,
                label=label,
                request_log_path=request_path,
                response_log_path=response_path,
                use_system_proxy=settings.use_system_proxy,
            )
        else:
            request_fields, _ = build_image_request_fields(
                prompt_text=prompt_text,
                settings=settings,
                image_model=selected_image_model,
                request_config=request_config,
                include_count=1,
            )
            request_payload = dict(request_fields)
            logger.log(
                f"{label}: "
                f"endpoint=/v1/images/generations, model={effective_image_model}, "
                f"resolution={request_config['output_resolution']}, "
                f"ratio={request_config['output_aspect_ratio']}, "
                f"size={request_config['size']}, "
                f"key_slot={image_key_slot}, "
                f"idempotency_key={idempotency_key}"
            )
            response_json = request_json(
                f"{gpt_image_request_api_base(settings, request_config['output_resolution'])}/v1/images/generations",
                request_payload,
                api_key=image_api_key,
                idempotency_key=idempotency_key,
                connect_timeout_seconds=settings.image_connect_timeout_seconds,
                read_timeout_seconds=settings.image_read_timeout_seconds,
                retry_count=settings.image_retry_count,
                logger=logger,
                label=label,
                request_log_path=request_path,
                response_log_path=response_path,
                use_system_proxy=settings.use_system_proxy,
            )
        return save_render_outputs(
            response_json,
            output_dir=output_dir,
            prompt_index=prompt_index,
            prompt_text=prompt_text,
            settings=settings,
            logger=logger,
            response_file=response_path,
        )


def count_rendered_images(manifest: list[dict[str, Any]]) -> int:
    return sum(len(item.get("images", [])) for item in manifest)


def export_run_zip(run_dir: Path) -> Path:
    zip_path = Path(
        shutil.make_archive(
            str(run_dir),
            "zip",
            root_dir=run_dir.parent,
            base_dir=run_dir.name,
        )
    )
    return zip_path


def run_image_edit_pipeline(
    context: AppContext,
    settings: Settings,
    options: ImageEditOptions,
    logger: AppLogger,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    prompt_text = options.prompt.strip()
    if not prompt_text:
        raise AppError("图片生成提示词不能为空。")
    selected_image_model = normalize_image_model(options.image_model)
    if not has_image_api_key_for_model(settings, selected_image_model):
        raise AppError("请先在设置页填写当前生图模型对应的 API Key。")
    request_count = max(1, int(options.images_per_prompt))

    run_paths = create_run_paths(context, options.project_name)
    run_dir = run_paths["run_dir"]
    json_dir = run_paths["json_dir"]
    images_dir = run_paths["images_dir"]
    run_logger = logger.with_run_log(json_dir / "run.log")
    run_logger.log(f"开始图片生成任务：project={options.project_name}")

    history_base = {
        "run_id": run_paths["run_id"],
        "project_name": options.project_name,
        "project_slug": run_paths["project_slug"],
        "task_key": "image-edit",
        "conversation_id": options.conversation_id,
        "conversation_title": options.conversation_title,
        "task_name": "图片生成",
        "run_date": run_paths["run_id"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "aspect_ratio": options.output_aspect_ratio,
        "output_resolution": options.output_resolution,
        "output_aspect_ratio": options.output_aspect_ratio,
        "resolved_size": "",
        "image_key_slot": "",
        "image_model": selected_image_model,
        "effective_image_model": "",
        "output_label": "",
        "prompt_count": 1,
        "images_per_prompt": request_count,
        "request_count": request_count,
        "images_per_request": 1,
        "concurrency": min(request_count, MAX_IMAGE_CONCURRENCY),
        "input_image_count": len(options.input_images),
    }

    try:
        input_images: list[Path] = []
        input_meta: list[dict[str, Any]] = []
        if options.input_images:
            input_images, input_meta = copy_image_edit_inputs(
                options.input_images,
                target_dir=json_dir / "input_images",
                logger=run_logger,
            )
        request_config = resolve_image_request_config(
            output_resolution=options.output_resolution,
            output_aspect_ratio=options.output_aspect_ratio,
            settings=settings,
            image_model=selected_image_model,
            input_images=input_images,
            logger=run_logger,
        )
        effective_image_model = resolve_effective_image_model(
            settings=settings,
            image_model=selected_image_model,
            output_resolution=request_config["output_resolution"],
            output_aspect_ratio=request_config["output_aspect_ratio"],
        )
        image_api_selection = resolve_image_api_selection(
            settings,
            request_config["output_resolution"],
            image_model=selected_image_model,
        )
        history_base = {
            **history_base,
            "aspect_ratio": request_config["output_aspect_ratio"],
            "output_resolution": request_config["output_resolution"],
            "output_aspect_ratio": request_config["output_aspect_ratio"],
            "resolved_size": request_config["size"],
            "image_key_slot": image_api_selection["key_slot"],
            "effective_image_model": effective_image_model,
            "output_label": request_config["label"],
        }
        write_json(json_dir / "sources.json", {"images": input_meta})
        write_json(json_dir / "settings.json", settings.to_public_dict())

        prompt_path = run_dir / "prompt.txt"
        prompt_path.write_text(prompt_text, encoding="utf-8")

        def build_summary(current_manifest: list[dict[str, Any]], status: str) -> dict[str, Any]:
            ordered_manifest = sorted(
                current_manifest,
                key=lambda item: int(item.get("index", 0)),
            )
            failed_renders = [
                item for item in ordered_manifest if item.get("status") == "failed"
            ]
            successful_renders = [
                item for item in ordered_manifest if item.get("status") != "failed"
            ]
            return {
                "project_name": options.project_name,
                "run_id": run_paths["run_id"],
                "run_dir": str(run_dir),
                "task_key": "image-edit",
                "task_name": "图片生成",
                "status": status,
                "created_at": history_base["created_at"],
                "prompt_count": 1,
                "request_count": request_count,
                "completed_request_count": len(successful_renders),
                "failed_request_count": len(failed_renders),
                "images_per_request": 1,
                "rendered_image_count": count_rendered_images(successful_renders),
                "aspect_ratio": request_config["output_aspect_ratio"],
                "output_resolution": request_config["output_resolution"],
                "output_aspect_ratio": request_config["output_aspect_ratio"],
                "resolved_size": request_config["size"],
                "image_key_slot": image_api_selection["key_slot"],
                "image_model": selected_image_model,
                "effective_image_model": effective_image_model,
                "output_label": request_config["label"],
                "prompts_file": str(prompt_path),
                "render_manifest_file": str(json_dir / "manifest.json"),
                "debug_log_file": str(json_dir / "run.log"),
                "input_images": input_meta,
                "errors": [item.get("error") for item in failed_renders if item.get("error")],
                "renders": ordered_manifest,
            }

        def publish_progress() -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(build_summary(manifest, "running"))
            except Exception as exc:
                run_logger.log(f"图片生成进度更新失败：{exc}")

        manifest: list[dict[str, Any]] = []
        max_workers = min(request_count, MAX_IMAGE_CONCURRENCY)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    render_image_edit,
                    prompt_text=prompt_text,
                    input_images=input_images,
                    settings=settings,
                    image_model=selected_image_model,
                    run_id=str(run_paths["run_id"]),
                    image_api_key=image_api_selection["api_key"],
                    image_key_slot=image_api_selection["key_slot"],
                    output_resolution=request_config["output_resolution"],
                    output_aspect_ratio=request_config["output_aspect_ratio"],
                    images_per_prompt=1,
                    output_dir=images_dir,
                    json_dir=json_dir,
                    logger=run_logger,
                    prompt_index=index,
                    request_file_stem=f"edit-{index:02d}",
                    endpoint_scope="image-edit",
                    label=f"image edit {index:02d}/{request_count}",
                ): index
                for index in range(1, request_count + 1)
            }
            for future in concurrent.futures.as_completed(futures):
                index = futures[future]
                try:
                    manifest.append(future.result())
                except Exception as exc:
                    error_text = str(exc)
                    run_logger.log(f"image edit {index:02d}/{request_count}: 生成失败：{error_text}")
                    manifest.append(
                        {
                            "index": index,
                            "prompt": prompt_text,
                            "status": "failed",
                            "error": error_text,
                            "images": [],
                            "image_details": [],
                        }
                    )
                manifest.sort(key=lambda item: int(item.get("index", 0)))
                write_json(json_dir / "manifest.json", manifest)
                publish_progress()
        manifest.sort(key=lambda item: int(item.get("index", 0)))
        write_json(json_dir / "manifest.json", manifest)

        successful_manifest = [item for item in manifest if item.get("status") != "failed"]
        failed_manifest = [item for item in manifest if item.get("status") == "failed"]
        if not successful_manifest:
            error_message = (
                failed_manifest[0].get("error")
                if failed_manifest
                else "所有图片生成请求都失败。"
            )
            raise AppError(str(error_message))
        final_status = "partial" if failed_manifest else "completed"
        summary = build_summary(manifest, final_status)
        if failed_manifest:
            summary["error"] = (
                f"{len(failed_manifest)} / {request_count} 个生成请求失败，"
                f"已保留 {summary['rendered_image_count']} 张成功图片。"
            )
        summary_path = json_dir / "summary.json"
        write_json(summary_path, summary)
        run_logger.log(f"图片生成任务{('部分完成' if failed_manifest else '完成')}：{summary_path}")

        record = {
            **history_base,
            "status": final_status,
            "error": summary.get("error", ""),
            "summary_file": str(summary_path),
            "render_manifest_file": summary["render_manifest_file"],
            "debug_log_file": summary["debug_log_file"],
            "input_images": input_meta,
            "rendered_image_count": summary["rendered_image_count"],
            "failed_request_count": summary["failed_request_count"],
            "image_key_slot": image_api_selection["key_slot"],
            "latest_images": [
                image_path
                for item in successful_manifest
                for image_path in item.get("images", [])
            ][:8],
        }
        context.append_history(record)
        return record
    except Exception as exc:
        logger.log(f"图片生成任务失败：{exc}")
        cleanup_failed_run_dir(context, run_dir)
        raise


def run_image_agent_pipeline(
    context: AppContext,
    settings: Settings,
    options: ImageAgentOptions,
    logger: AppLogger,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    if not resolve_secret_value(settings.image_agent_api_key):
        raise AppError("请先在设置页填写有效的 Agent 大模型 API Key。")
    user_prompt = options.prompt.strip()
    if not user_prompt:
        raise AppError("Agent 模式需要填写图片生成需求。")

    selected_image_model = normalize_image_model(options.image_model)
    configured_agent_resolutions = image_agent_allowed_resolutions_for_settings(
        settings,
        selected_image_model,
    )
    agent_allowed_resolutions = configured_agent_resolutions or image_agent_allowed_resolutions(
        selected_image_model
    )
    agent_default_resolution = image_agent_default_output_resolution(
        selected_image_model
    )
    agent_prompt_mentions_resolution = user_prompt_mentions_output_resolution(
        user_prompt
    )
    agent_prompt_allowed_resolutions = image_agent_resolutions_for_prompt(
        user_prompt=user_prompt,
        image_model=selected_image_model,
        available_resolutions=agent_allowed_resolutions,
    )
    planner_allowed_resolutions = (
        agent_prompt_allowed_resolutions
        or configured_agent_resolutions
        or image_agent_allowed_resolutions(selected_image_model)
    )
    request_config = {
        "output_resolution": "agent",
        "output_aspect_ratio": "agent",
        "size": "agent",
        "label": "Agent 自动",
    }
    effective_image_model = image_agent_effective_model_hint(
        settings=settings,
        image_model=selected_image_model,
        output_resolution=request_config["output_resolution"],
        output_aspect_ratio=request_config["output_aspect_ratio"],
    )
    image_api_selection = {"api_key": "", "key_slot": "pending"}

    run_paths = create_run_paths(context, options.project_name)
    run_dir = run_paths["run_dir"]
    json_dir = run_paths["json_dir"]
    images_dir = run_paths["images_dir"]
    run_logger = logger.with_run_log(json_dir / "run.log")
    run_logger.log(f"开始图片 Agent 任务：project={options.project_name}")
    (
        conversation_context_text,
        conversation_context_meta,
        context_image_refs,
    ) = resolve_agent_conversation_context(context, options)
    if conversation_context_text:
        (run_dir / "agent-context.md").write_text(
            conversation_context_text + "\n",
            encoding="utf-8",
        )
    write_json(
        json_dir / "agent-context.json",
        {
            "meta": conversation_context_meta,
            "context": conversation_context_text,
            "image_refs": [
                {
                    **{key: value for key, value in ref.items() if key != "path"},
                    "path": str(ref.get("path") or ""),
                }
                for ref in context_image_refs
            ],
        },
    )
    run_logger.log(
        "Agent 上下文："
        f"source={conversation_context_meta.get('source')}, "
        f"messages={conversation_context_meta.get('message_count')}, "
        f"image_refs={conversation_context_meta.get('image_ref_count')}, "
        f"compression={conversation_context_meta.get('compression')}, "
        f"estimated_tokens={conversation_context_meta.get('estimated_tokens')}"
    )

    plan: dict[str, Any] = {}
    design_strategy = ""
    prompt_items: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []

    history_base = {
        "run_id": run_paths["run_id"],
        "project_name": options.project_name,
        "project_slug": run_paths["project_slug"],
        "task_key": "image-agent",
        "conversation_id": options.conversation_id,
        "conversation_title": options.conversation_title,
        "task_name": "图片生成 Agent",
        "run_date": run_paths["run_id"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "aspect_ratio": request_config["output_aspect_ratio"],
        "output_resolution": request_config["output_resolution"],
        "output_aspect_ratio": request_config["output_aspect_ratio"],
        "resolved_size": request_config["size"],
        "image_key_slot": image_api_selection["key_slot"],
        "image_model": selected_image_model,
        "effective_image_model": effective_image_model,
        "image_agent_model": settings.image_agent_model,
        "output_label": request_config["label"],
        "prompt_count": 0,
        "images_per_prompt": 1,
        "images_per_request": 1,
        "input_image_count": len(options.input_images),
        "default_output_resolution": agent_default_resolution,
        "user_specified_output_resolution": agent_prompt_mentions_resolution,
        "conversation_context_message_count": conversation_context_meta.get(
            "message_count",
            0,
        ),
    }

    def build_summary(status: str, phase: str) -> dict[str, Any]:
        ordered_manifest = sorted(
            manifest,
            key=lambda item: int(item.get("index", 0)),
        )
        image_count = (
            bounded_agent_image_count_or_zero(plan.get("image_count")) if plan else 0
        )
        return {
            "project_name": options.project_name,
            "run_id": run_paths["run_id"],
            "run_dir": str(run_dir),
            "task_key": "image-agent",
            "task_name": "图片生成 Agent",
            "status": status,
            "phase": phase,
            "prompt": user_prompt,
            "created_at": history_base["created_at"],
            "prompt_count": image_count,
            "request_count": image_count,
            "completed_request_count": len(ordered_manifest),
            "images_per_prompt": 1,
            "images_per_request": 1,
            "rendered_image_count": count_rendered_images(ordered_manifest),
            "aspect_ratio": request_config["output_aspect_ratio"],
            "output_resolution": request_config["output_resolution"],
            "output_aspect_ratio": request_config["output_aspect_ratio"],
            "resolved_size": request_config["size"],
            "image_key_slot": image_api_selection["key_slot"],
            "image_model": selected_image_model,
            "effective_image_model": effective_image_model,
            "image_agent_model": settings.image_agent_model,
            "output_label": request_config["label"],
            "prompts_file": str(run_dir / "prompts.txt"),
            "conversation_context_file": str(run_dir / "agent-context.md")
            if conversation_context_text
            else "",
            "render_manifest_file": str(json_dir / "manifest.json"),
            "debug_log_file": str(json_dir / "run.log"),
            "input_images": input_meta,
            "agent": {
                "model": settings.image_agent_model,
                "phase": phase,
                "context": conversation_context_meta,
                "plan": plan,
                "response_text": design_strategy if not plan.get("needs_image", True) else "",
                "design_strategy": design_strategy,
                "prompts": prompt_items,
            },
            "renders": ordered_manifest,
        }

    def publish_progress(phase: str) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(build_summary("running", phase))
        except Exception as exc:
            run_logger.log(f"图片 Agent 进度更新失败：{exc}")

    try:
        input_images: list[Path] = []
        input_meta: list[dict[str, Any]] = []
        if options.input_images:
            input_images, input_meta = copy_image_edit_inputs(
                options.input_images,
                target_dir=json_dir / "input_images",
                logger=run_logger,
            )
        write_json(json_dir / "sources.json", {"images": input_meta})
        write_json(json_dir / "settings.json", settings.to_public_dict())
        (run_dir / "user-goal.txt").write_text(user_prompt + "\n", encoding="utf-8")

        plan, _ = generate_image_agent_plan(
            settings,
            user_prompt=user_prompt,
            input_images=input_images,
            context_image_refs=context_image_refs,
            selected_image_model=selected_image_model,
            effective_image_model=effective_image_model,
            request_config=request_config,
            allowed_resolutions=planner_allowed_resolutions,
            default_resolution=agent_default_resolution,
            conversation_context=conversation_context_text,
            run_dir=run_dir,
            json_dir=json_dir,
            logger=run_logger,
        )
        if not plan.get("needs_image", True):
            design_strategy = str(plan.get("response_text") or plan.get("summary") or "").strip()
            (run_dir / "agent-reply.md").write_text(design_strategy + "\n", encoding="utf-8")
            write_json(json_dir / "manifest.json", manifest)
            summary = build_summary("completed", "completed")
            summary_path = json_dir / "summary.json"
            write_json(summary_path, summary)
            run_logger.log(f"Agent 文本回复完成：{summary_path}")
            record = {
                **history_base,
                "status": "completed",
                "prompt": user_prompt,
                "summary_file": str(summary_path),
                "render_manifest_file": summary["render_manifest_file"],
                "debug_log_file": summary["debug_log_file"],
                "input_images": input_meta,
                "rendered_image_count": 0,
                "image_key_slot": image_api_selection["key_slot"],
                "latest_images": [],
            }
            context.append_history(record)
            return record

        if not configured_agent_resolutions:
            raise AppError("请先在设置页填写当前生图模型对应的 API Key。")
        if not agent_prompt_allowed_resolutions:
            raise AppError(
                f"Agent 默认使用 {agent_default_resolution.upper()}，但当前模型没有配置对应 API Key。"
            )
        request_config = resolve_image_agent_request_config(
            plan,
            image_model=selected_image_model,
            settings=settings,
            allowed_resolutions=agent_prompt_allowed_resolutions,
            input_images=input_images,
            logger=run_logger,
        )
        effective_image_model = resolve_effective_image_model(
            settings=settings,
            image_model=selected_image_model,
            output_resolution=request_config["output_resolution"],
            output_aspect_ratio=request_config["output_aspect_ratio"],
        )
        image_api_selection = resolve_image_api_selection(
            settings,
            request_config["output_resolution"],
            image_model=selected_image_model,
        )
        history_base.update(
            {
                "aspect_ratio": request_config["output_aspect_ratio"],
                "output_resolution": request_config["output_resolution"],
                "output_aspect_ratio": request_config["output_aspect_ratio"],
                "resolved_size": request_config["size"],
                "image_key_slot": image_api_selection["key_slot"],
                "effective_image_model": effective_image_model,
                "output_label": request_config["label"],
            }
        )
        run_logger.log(
            "Agent 输出规格："
            f"resolution={request_config['output_resolution']}, "
            f"ratio={request_config['output_aspect_ratio']}, "
            f"size={request_config['size']}"
        )
        publish_progress("planned")

        design_strategy, prompt_items, _ = generate_image_agent_design(
            settings,
            user_prompt=user_prompt,
            input_images=input_images,
            context_image_refs=context_image_refs,
            selected_image_model=selected_image_model,
            effective_image_model=effective_image_model,
            request_config=request_config,
            allowed_resolutions=agent_prompt_allowed_resolutions,
            default_resolution=agent_default_resolution,
            plan=plan,
            conversation_context=conversation_context_text,
            run_dir=run_dir,
            json_dir=json_dir,
            logger=run_logger,
        )
        input_image_registry = build_agent_input_image_registry(
            input_images,
            context_image_refs,
        )
        prompt_items = enrich_image_agent_prompt_items(
            prompt_items,
            default_request_config=request_config,
            image_model=selected_image_model,
            settings=settings,
            allowed_resolutions=agent_prompt_allowed_resolutions,
            input_image_registry=input_image_registry,
            user_prompt=user_prompt,
            current_input_images=input_images,
            context_image_refs=context_image_refs,
            logger=run_logger,
        )
        request_config = summarize_agent_request_config(prompt_items, request_config)
        history_base.update(
            {
                "aspect_ratio": request_config["output_aspect_ratio"],
                "output_resolution": request_config["output_resolution"],
                "output_aspect_ratio": request_config["output_aspect_ratio"],
                "resolved_size": request_config["size"],
                "output_label": request_config["label"],
            }
        )
        prompts = [item["prompt"] for item in prompt_items]
        prompt_path = run_dir / "prompts.txt"
        prompt_path.write_text(format_prompt_lines(prompts), encoding="utf-8")
        history_base["prompt_count"] = len(prompts)
        history_base["request_count"] = len(prompts)
        history_base["concurrency"] = min(len(prompts), MAX_IMAGE_CONCURRENCY)
        publish_progress("designed")

        max_workers = min(len(prompts), MAX_IMAGE_CONCURRENCY)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures: dict[concurrent.futures.Future[dict[str, Any]], dict[str, Any]] = {}
            for item in prompt_items:
                item_index = int(item.get("index") or len(futures) + 1)
                item_input_images = select_agent_render_input_images(
                    item,
                    user_prompt=user_prompt,
                    current_input_images=input_images,
                    context_image_refs=context_image_refs,
                    input_image_registry=input_image_registry,
                )
                item_config = resolve_image_agent_prompt_item_config(
                    item,
                    default_request_config=request_config,
                    image_model=selected_image_model,
                    settings=settings,
                    allowed_resolutions=agent_prompt_allowed_resolutions,
                    input_images=item_input_images,
                    logger=run_logger,
                )
                item_effective_model = resolve_effective_image_model(
                    settings=settings,
                    image_model=selected_image_model,
                    output_resolution=item_config["output_resolution"],
                    output_aspect_ratio=item_config["output_aspect_ratio"],
                )
                item_api_selection = resolve_image_api_selection(
                    settings,
                    item_config["output_resolution"],
                    image_model=selected_image_model,
                )
                future = executor.submit(
                    render_image_edit,
                    prompt_text=str(item.get("prompt") or ""),
                    input_images=item_input_images,
                    settings=settings,
                    image_model=selected_image_model,
                    run_id=str(run_paths["run_id"]),
                    image_api_key=item_api_selection["api_key"],
                    image_key_slot=item_api_selection["key_slot"],
                    output_resolution=item_config["output_resolution"],
                    output_aspect_ratio=item_config["output_aspect_ratio"],
                    images_per_prompt=1,
                    output_dir=images_dir,
                    json_dir=json_dir,
                    logger=run_logger,
                    prompt_index=item_index,
                    request_file_stem=f"agent-{item_index:02d}",
                    endpoint_scope="image-agent",
                    label=f"image agent {item_index:02d}/{len(prompts)}",
                )
                futures[future] = {
                    "title": str(item.get("title") or f"图片 {item_index}"),
                    "output_resolution": item_config["output_resolution"],
                    "output_aspect_ratio": item_config["output_aspect_ratio"],
                    "resolved_size": item_config["size"],
                    "output_label": item_config["label"],
                    "image_key_slot": item_api_selection["key_slot"],
                    "effective_image_model": item_effective_model,
                    "input_image_ids": [
                        str(value).strip()
                        for value in item.get("input_images", [])
                        if str(value).strip()
                    ]
                    if isinstance(item.get("input_images"), list)
                    else [],
                    "input_image_count": len(item_input_images),
                }
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                result.update(futures[future])
                manifest.append(result)
                manifest.sort(key=lambda item: int(item.get("index", 0)))
                write_json(json_dir / "manifest.json", manifest)
                publish_progress("rendering")

        manifest.sort(key=lambda item: int(item.get("index", 0)))
        write_json(json_dir / "manifest.json", manifest)

        summary = build_summary("completed", "completed")
        summary_path = json_dir / "summary.json"
        write_json(summary_path, summary)
        run_logger.log(f"图片 Agent 任务完成：{summary_path}")

        record = {
            **history_base,
            "status": "completed",
            "prompt": user_prompt,
            "summary_file": str(summary_path),
            "render_manifest_file": summary["render_manifest_file"],
            "debug_log_file": summary["debug_log_file"],
            "input_images": input_meta,
            "rendered_image_count": summary["rendered_image_count"],
            "image_key_slot": image_api_selection["key_slot"],
            "latest_images": [
                image_path
                for item in manifest
                for image_path in item.get("images", [])
            ][:8],
        }
        context.append_history(record)
        return record
    except Exception as exc:
        logger.log(f"图片 Agent 任务失败：{exc}")
        diagnostics_dir = preserve_failed_run_diagnostics(
            context,
            run_dir,
            label="image-agent",
        )
        if diagnostics_dir is not None:
            logger.log(f"图片 Agent 失败诊断已保留：{diagnostics_dir}")
        cleanup_failed_run_dir(context, run_dir)
        raise


def run_color_match_pipeline(
    context: AppContext,
    settings: Settings,
    options: ColorMatchOptions,
    logger: AppLogger,
) -> dict[str, Any]:
    if not resolve_secret_value(settings.color_match_api_key):
        raise AppError("请先在设置页填写有效的追色大模型 API Key。")

    selected_image_model = image_model_from_settings(settings)
    if not has_image_api_key_for_model(settings, selected_image_model):
        raise AppError("请先在设置页填写当前生图模型对应的 API Key。")
    analysis_image_config = resolve_image_request_config(
        output_resolution="1k",
        output_aspect_ratio="4:3",
        settings=settings,
    )
    analysis_effective_image_model = resolve_effective_image_model(
        settings=settings,
        image_model=selected_image_model,
        output_resolution=analysis_image_config["output_resolution"],
        output_aspect_ratio=analysis_image_config["output_aspect_ratio"],
    )
    analysis_image_api_selection = resolve_image_api_selection(
        settings,
        analysis_image_config["output_resolution"],
        image_model=selected_image_model,
    )

    run_paths = create_run_paths(context, options.project_name)
    run_dir = run_paths["run_dir"]
    json_dir = run_paths["json_dir"]
    images_dir = run_paths["images_dir"]
    run_logger = logger.with_run_log(json_dir / "run.log")
    run_logger.log(f"开始一键追色任务：project={options.project_name}")

    history_base = {
        "run_id": run_paths["run_id"],
        "project_name": options.project_name,
        "project_slug": run_paths["project_slug"],
        "task_key": "color-match",
        "task_name": "一键追色",
        "run_date": run_paths["run_id"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "aspect_ratio": options.output_aspect_ratio,
        "output_resolution": options.output_resolution,
        "output_aspect_ratio": options.output_aspect_ratio,
        "resolved_size": "",
        "image_key_slot": "",
        "image_model": selected_image_model,
        "effective_image_model": "",
        "analysis_effective_image_model": analysis_effective_image_model,
        "output_label": "",
        "prompt_count": 2,
        "images_per_prompt": 1,
        "concurrency": 2,
        "input_image_count": 2,
    }

    try:
        input_dir = json_dir / "input_images"
        tone_image, tone_meta = copy_named_input_image(
            options.tone_image,
            target_dir=input_dir,
            stem="tone-reference",
            label="色调参考图",
            logger=run_logger,
        )
        scene_image, scene_meta = copy_named_input_image(
            options.scene_image,
            target_dir=input_dir,
            stem="scene",
            label="静物场景图",
            logger=run_logger,
        )
        desaturated_scene = desaturate_image(
            scene_image,
            images_dir / "scene-desaturated.png",
            logger=run_logger,
        )
        desaturated_scene_thumbnail = create_image_thumbnail(
            desaturated_scene,
            logger=run_logger,
        )
        request_config = resolve_image_request_config(
            output_resolution=options.output_resolution,
            output_aspect_ratio=options.output_aspect_ratio,
            settings=settings,
            image_model=selected_image_model,
            input_images=[desaturated_scene],
            logger=run_logger,
        )
        effective_image_model = resolve_effective_image_model(
            settings=settings,
            image_model=selected_image_model,
            output_resolution=request_config["output_resolution"],
            output_aspect_ratio=request_config["output_aspect_ratio"],
        )
        image_api_selection = resolve_image_api_selection(
            settings,
            request_config["output_resolution"],
            image_model=selected_image_model,
        )
        history_base = {
            **history_base,
            "aspect_ratio": request_config["output_aspect_ratio"],
            "output_resolution": request_config["output_resolution"],
            "output_aspect_ratio": request_config["output_aspect_ratio"],
            "resolved_size": request_config["size"],
            "image_key_slot": image_api_selection["key_slot"],
            "effective_image_model": effective_image_model,
            "output_label": request_config["label"],
        }
        write_json(
            json_dir / "sources.json",
            {
                "tone": tone_meta,
                "scene": scene_meta,
                "desaturated_scene": str(desaturated_scene),
            },
        )
        write_json(json_dir / "settings.json", settings.to_public_dict())

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            analysis_future = executor.submit(
                generate_color_analysis_text,
                settings,
                tone_image=tone_image,
                run_dir=run_dir,
                json_dir=json_dir,
                logger=run_logger,
            )
            analysis_image_future = executor.submit(
                render_image_edit,
                prompt_text=COLOR_ANALYSIS_IMAGE_PROMPT,
                input_images=[tone_image],
                settings=settings,
                image_model=selected_image_model,
                run_id=str(run_paths["run_id"]),
                image_api_key=analysis_image_api_selection["api_key"],
                image_key_slot=analysis_image_api_selection["key_slot"],
                output_resolution=analysis_image_config["output_resolution"],
                output_aspect_ratio=analysis_image_config["output_aspect_ratio"],
                images_per_prompt=1,
                output_dir=images_dir,
                json_dir=json_dir,
                logger=run_logger,
                prompt_index=1,
                request_file_stem="color-analysis-image",
                endpoint_scope="color-analysis-image",
                label="color analysis image",
            )
            analysis_text = analysis_future.result()
            analysis_image_render = analysis_image_future.result()

        analysis_images = analysis_image_render.get("images") or []
        if not analysis_images:
            raise AppError("色彩分析图片生成成功但没有返回可用图片。")
        analysis_image_path = Path(str(analysis_images[0])).expanduser().resolve()
        colorize_from_text_prompt = (
            f"{analysis_text.strip()}\n{COLORIZE_WITH_ANALYSIS_PROMPT}"
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            text_colorize_future = executor.submit(
                render_image_edit,
                prompt_text=colorize_from_text_prompt,
                input_images=[desaturated_scene],
                settings=settings,
                image_model=selected_image_model,
                run_id=str(run_paths["run_id"]),
                image_api_key=image_api_selection["api_key"],
                image_key_slot=image_api_selection["key_slot"],
                output_resolution=request_config["output_resolution"],
                output_aspect_ratio=request_config["output_aspect_ratio"],
                images_per_prompt=1,
                output_dir=images_dir,
                json_dir=json_dir,
                logger=run_logger,
                prompt_index=2,
                request_file_stem="colorize-from-text",
                endpoint_scope="colorize-from-text",
                label="colorize from analysis text",
            )
            image_colorize_future = executor.submit(
                render_image_edit,
                prompt_text=COLORIZE_PROMPT,
                input_images=[desaturated_scene, analysis_image_path],
                settings=settings,
                image_model=selected_image_model,
                run_id=str(run_paths["run_id"]),
                image_api_key=image_api_selection["api_key"],
                image_key_slot=image_api_selection["key_slot"],
                output_resolution=request_config["output_resolution"],
                output_aspect_ratio=request_config["output_aspect_ratio"],
                images_per_prompt=1,
                output_dir=images_dir,
                json_dir=json_dir,
                logger=run_logger,
                prompt_index=3,
                request_file_stem="colorize-from-analysis-image",
                endpoint_scope="colorize-from-analysis-image",
                label="colorize from analysis image",
            )
            text_colorize_render = text_colorize_future.result()
            image_colorize_render = image_colorize_future.result()

        manifest = [
            text_colorize_render,
            image_colorize_render,
            analysis_image_render,
        ]
        color_match_outputs = {
            "text_route": {
                "label": "大模型路线结果",
                "prompt": colorize_from_text_prompt,
                "images": text_colorize_render.get("images", []),
            },
            "text_route_prompt": colorize_from_text_prompt,
            "image_route": {
                "label": "第二路线生成结果",
                "prompt": COLORIZE_PROMPT,
                "images": image_colorize_render.get("images", []),
            },
            "analysis_image": {
                "label": "第二路线参考色板图",
                "prompt": COLOR_ANALYSIS_IMAGE_PROMPT,
                "images": analysis_image_render.get("images", []),
            },
            "desaturated_scene": {
                "label": "去色输入图",
                "images": [str(desaturated_scene)],
            },
        }
        write_json(json_dir / "manifest.json", manifest)

        summary = {
            "project_name": options.project_name,
            "run_id": run_paths["run_id"],
            "run_dir": str(run_dir),
            "task_key": "color-match",
            "task_name": "一键追色",
            "created_at": history_base["created_at"],
            "prompt_count": 2,
            "rendered_image_count": count_rendered_images(manifest),
            "final_rendered_image_count": count_rendered_images(
                [text_colorize_render, image_colorize_render]
            ),
            "aspect_ratio": request_config["output_aspect_ratio"],
            "output_resolution": request_config["output_resolution"],
            "output_aspect_ratio": request_config["output_aspect_ratio"],
            "resolved_size": request_config["size"],
            "image_key_slot": image_api_selection["key_slot"],
            "analysis_image_key_slot": analysis_image_api_selection["key_slot"],
            "image_model": selected_image_model,
            "effective_image_model": effective_image_model,
            "analysis_effective_image_model": analysis_effective_image_model,
            "output_label": request_config["label"],
            "analysis_image_output_label": analysis_image_config["label"],
            "color_analysis_file": str(run_dir / "color-analysis.md"),
            "color_analysis_text": analysis_text,
            "desaturated_scene": str(desaturated_scene),
            "desaturated_scene_thumbnail": desaturated_scene_thumbnail,
            "color_match_outputs": color_match_outputs,
            "render_manifest_file": str(json_dir / "manifest.json"),
            "debug_log_file": str(json_dir / "run.log"),
            "input_images": [tone_meta, scene_meta],
            "renders": manifest,
        }
        summary_path = json_dir / "summary.json"
        write_json(summary_path, summary)
        run_logger.log(f"一键追色任务完成：{summary_path}")

        record = {
            **history_base,
            "status": "completed",
            "summary_file": str(summary_path),
            "render_manifest_file": summary["render_manifest_file"],
            "debug_log_file": summary["debug_log_file"],
            "input_images": [tone_meta, scene_meta],
            "rendered_image_count": summary["rendered_image_count"],
            "final_rendered_image_count": summary["final_rendered_image_count"],
            "image_key_slot": image_api_selection["key_slot"],
            "latest_images": [
                image_path
                for image_path in (
                    text_colorize_render.get("images", [])
                    + image_colorize_render.get("images", [])
                    + analysis_image_render.get("images", [])
                    + [str(desaturated_scene)]
                )
            ][:8],
        }
        context.append_history(record)
        return record
    except Exception as exc:
        logger.log(f"一键追色任务失败：{exc}")
        cleanup_failed_run_dir(context, run_dir)
        raise


def run_pipeline(
    context: AppContext,
    settings: Settings,
    options: RunOptions,
    logger: AppLogger,
) -> dict[str, Any]:
    if not settings.llm_api_key or settings.llm_api_key == "replace-me":
        raise AppError("请先在设置页填写有效的大模型 API Key。")
    selected_image_model = image_model_from_settings(settings)
    if not has_image_api_key_for_model(settings, selected_image_model):
        raise AppError("请先在设置页填写当前生图模型对应的 API Key。")

    run_paths = create_run_paths(context, options.project_name)
    run_dir = run_paths["run_dir"]
    json_dir = run_paths["json_dir"]
    images_dir = run_paths["images_dir"]
    run_logger = logger.with_run_log(json_dir / "run.log")
    run_logger.log(f"开始任务：project={options.project_name}")

    history_base = {
        "run_id": run_paths["run_id"],
        "project_name": options.project_name,
        "project_slug": run_paths["project_slug"],
        "run_date": run_paths["run_id"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "aspect_ratio": options.output_aspect_ratio,
        "output_resolution": options.output_resolution,
        "output_aspect_ratio": options.output_aspect_ratio,
        "resolved_size": "",
        "image_key_slot": "",
        "image_model": selected_image_model,
        "effective_image_model": "",
        "output_label": "",
        "prompt_count": options.prompt_count,
        "images_per_prompt": options.images_per_prompt,
        "concurrency": options.concurrency,
        "style_reference_count": source_spec_count(options.style_source),
        "product_reference_count": source_spec_count(options.product_source),
    }

    try:
        style_images, style_meta = resolve_reference_sources(
            "style",
            options.style_source,
            target_dir=images_dir,
            settings=settings,
            logger=run_logger,
            max_count=MAX_STYLE_REFERENCE_IMAGES,
        )
        product_images, product_meta = resolve_reference_sources(
            "product",
            options.product_source,
            target_dir=images_dir,
            settings=settings,
            logger=run_logger,
            max_count=MAX_PRODUCT_REFERENCE_IMAGES,
        )
        request_config = resolve_image_request_config(
            output_resolution=options.output_resolution,
            output_aspect_ratio=options.output_aspect_ratio,
            settings=settings,
            image_model=selected_image_model,
            input_images=product_images,
            logger=run_logger,
        )
        effective_image_model = resolve_effective_image_model(
            settings=settings,
            image_model=selected_image_model,
            output_resolution=request_config["output_resolution"],
            output_aspect_ratio=request_config["output_aspect_ratio"],
        )
        image_api_selection = resolve_image_api_selection(
            settings,
            request_config["output_resolution"],
            image_model=selected_image_model,
        )
        history_base = {
            **history_base,
            "aspect_ratio": request_config["output_aspect_ratio"],
            "output_resolution": request_config["output_resolution"],
            "output_aspect_ratio": request_config["output_aspect_ratio"],
            "resolved_size": request_config["size"],
            "image_key_slot": image_api_selection["key_slot"],
            "effective_image_model": effective_image_model,
            "output_label": request_config["label"],
        }
        write_json(
            json_dir / "sources.json",
            {
                "style": style_meta,
                "product": product_meta,
            },
        )
        write_json(
            json_dir / "settings.json",
            settings.to_public_dict(),
        )

        prompts, _ = generate_prompts(
            settings,
            style_images=style_images,
            product_images=product_images,
            prompt_count=options.prompt_count,
            user_prompt=options.user_prompt,
            run_dir=run_dir,
            json_dir=json_dir,
            logger=run_logger,
        )
        manifest = render_prompts(
            prompts,
            settings=settings,
            run_id=str(run_paths["run_id"]),
            product_images=product_images,
            image_api_key=image_api_selection["api_key"],
            image_key_slot=image_api_selection["key_slot"],
            output_resolution=request_config["output_resolution"],
            output_aspect_ratio=request_config["output_aspect_ratio"],
            images_per_prompt=options.images_per_prompt,
            concurrency=options.concurrency,
            output_dir=images_dir,
            json_dir=json_dir,
            logger=run_logger,
        )

        summary = {
            "project_name": options.project_name,
            "run_id": run_paths["run_id"],
            "run_dir": str(run_dir),
            "created_at": history_base["created_at"],
            "prompt_count": len(prompts),
            "rendered_image_count": count_rendered_images(manifest),
            "aspect_ratio": request_config["output_aspect_ratio"],
            "output_resolution": request_config["output_resolution"],
            "output_aspect_ratio": request_config["output_aspect_ratio"],
            "resolved_size": request_config["size"],
            "image_key_slot": image_api_selection["key_slot"],
            "image_model": selected_image_model,
            "effective_image_model": effective_image_model,
            "output_label": request_config["label"],
            "prompts_file": str(run_dir / "prompts.txt"),
            "prompt_request_file": str(json_dir / "prompt.request.json"),
            "prompt_response_file": str(json_dir / "prompt.response.json"),
            "render_manifest_file": str(json_dir / "manifest.json"),
            "debug_log_file": str(json_dir / "run.log"),
            "style_reference_count": len(style_images),
            "product_reference_count": len(product_images),
            "renders": manifest,
        }
        summary_path = json_dir / "summary.json"
        write_json(summary_path, summary)
        run_logger.log(f"任务完成：{summary_path}")

        record = {
            **history_base,
            "status": "completed",
            "summary_file": str(summary_path),
            "render_manifest_file": summary["render_manifest_file"],
            "debug_log_file": summary["debug_log_file"],
            "style_source": style_meta[0] if style_meta else {},
            "product_source": product_meta[0] if product_meta else {},
            "style_sources": style_meta,
            "product_sources": product_meta,
            "rendered_image_count": summary["rendered_image_count"],
            "image_key_slot": image_api_selection["key_slot"],
            "latest_images": [
                image_path
                for item in manifest
                for image_path in item.get("images", [])
            ][:8],
        }
        context.append_history(record)
        return record
    except Exception as exc:
        logger.log(f"任务失败：{exc}")
        cleanup_failed_run_dir(context, run_dir)
        raise


def run_style_replicate2_pipeline(
    context: AppContext,
    settings: Settings,
    options: StyleReplicate2Options,
    logger: AppLogger,
) -> dict[str, Any]:
    if not settings.llm_api_key or settings.llm_api_key == "replace-me":
        raise AppError("请先在设置页填写有效的大模型 API Key。")
    selected_image_model = image_model_from_settings(settings)
    if not has_image_api_key_for_model(settings, selected_image_model):
        raise AppError("请先在设置页填写当前生图模型对应的 API Key。")

    run_paths = create_run_paths(context, options.project_name)
    run_dir = run_paths["run_dir"]
    json_dir = run_paths["json_dir"]
    images_dir = run_paths["images_dir"]
    run_logger = logger.with_run_log(json_dir / "run.log")
    run_logger.log(f"开始复刻风格图片2任务：project={options.project_name}")

    history_base = {
        "task_key": "style-replicate-v2",
        "task_name": "复刻风格图片2",
        "run_id": run_paths["run_id"],
        "project_name": options.project_name,
        "project_slug": run_paths["project_slug"],
        "run_date": run_paths["run_id"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "aspect_ratio": options.output_aspect_ratio,
        "output_resolution": options.output_resolution,
        "output_aspect_ratio": options.output_aspect_ratio,
        "resolved_size": "",
        "image_key_slot": "",
        "image_model": selected_image_model,
        "effective_image_model": "",
        "output_label": "",
        "prompt_count": options.prompt_count,
        "images_per_prompt": options.images_per_prompt,
        "concurrency": options.concurrency,
        "reference_count": source_spec_count(options.reference_source),
        "style_reference_count": source_spec_count(options.reference_source),
        "product_reference_count": 0,
    }

    try:
        reference_images, reference_meta = resolve_reference_sources(
            "reference",
            options.reference_source,
            target_dir=images_dir,
            settings=settings,
            logger=run_logger,
            max_count=MAX_STYLE_REPLICATE2_REFERENCE_IMAGES,
        )
        request_config = resolve_image_request_config(
            output_resolution=options.output_resolution,
            output_aspect_ratio=options.output_aspect_ratio,
            settings=settings,
            image_model=selected_image_model,
            input_images=reference_images,
            logger=run_logger,
        )
        effective_image_model = resolve_effective_image_model(
            settings=settings,
            image_model=selected_image_model,
            output_resolution=request_config["output_resolution"],
            output_aspect_ratio=request_config["output_aspect_ratio"],
        )
        image_api_selection = resolve_image_api_selection(
            settings,
            request_config["output_resolution"],
            image_model=selected_image_model,
        )
        history_base = {
            **history_base,
            "aspect_ratio": request_config["output_aspect_ratio"],
            "output_resolution": request_config["output_resolution"],
            "output_aspect_ratio": request_config["output_aspect_ratio"],
            "resolved_size": request_config["size"],
            "image_key_slot": image_api_selection["key_slot"],
            "effective_image_model": effective_image_model,
            "output_label": request_config["label"],
        }
        write_json(
            json_dir / "sources.json",
            {
                "reference": reference_meta,
            },
        )
        write_json(
            json_dir / "settings.json",
            settings.to_public_dict(),
        )

        prompts, _ = generate_style_replicate2_prompts(
            settings,
            reference_images=reference_images,
            prompt_count=options.prompt_count,
            user_prompt=options.user_prompt,
            run_dir=run_dir,
            json_dir=json_dir,
            logger=run_logger,
        )
        upload_gate: threading.Semaphore | None = None
        if len(reference_images) > STYLE_REPLICATE2_UPLOAD_GATE_REFERENCE_THRESHOLD:
            upload_gate = threading.Semaphore(STYLE_REPLICATE2_UPLOAD_CONCURRENCY_LIMIT)
            run_logger.log(
                "复刻风格图片2多参考图上传已自动限流："
                f"单任务参考图 {len(reference_images)} 张，超过 "
                f"{STYLE_REPLICATE2_UPLOAD_GATE_REFERENCE_THRESHOLD} 张；"
                f"仅限制上传阶段并发为 {STYLE_REPLICATE2_UPLOAD_CONCURRENCY_LIMIT}，"
                "上传完成后立即释放槽位，生成等待阶段不占用上传槽。"
            )
        manifest = render_prompts(
            prompts,
            settings=settings,
            run_id=str(run_paths["run_id"]),
            product_images=reference_images,
            image_api_key=image_api_selection["api_key"],
            image_key_slot=image_api_selection["key_slot"],
            output_resolution=request_config["output_resolution"],
            output_aspect_ratio=request_config["output_aspect_ratio"],
            images_per_prompt=options.images_per_prompt,
            concurrency=options.concurrency,
            output_dir=images_dir,
            json_dir=json_dir,
            logger=run_logger,
            reference_prompt_prefix=STYLE_REPLICATE2_RENDER_PROMPT_PREFIX,
            endpoint_scope="style-replicate-v2",
            upload_gate=upload_gate,
        )

        summary = {
            "project_name": options.project_name,
            "run_id": run_paths["run_id"],
            "run_dir": str(run_dir),
            "created_at": history_base["created_at"],
            "prompt_count": len(prompts),
            "rendered_image_count": count_rendered_images(manifest),
            "aspect_ratio": request_config["output_aspect_ratio"],
            "output_resolution": request_config["output_resolution"],
            "output_aspect_ratio": request_config["output_aspect_ratio"],
            "resolved_size": request_config["size"],
            "image_key_slot": image_api_selection["key_slot"],
            "image_model": selected_image_model,
            "effective_image_model": effective_image_model,
            "output_label": request_config["label"],
            "prompts_file": str(run_dir / "prompts.txt"),
            "prompt_request_file": str(json_dir / "prompt.request.json"),
            "prompt_response_file": str(json_dir / "prompt.response.json"),
            "render_manifest_file": str(json_dir / "manifest.json"),
            "debug_log_file": str(json_dir / "run.log"),
            "reference_count": len(reference_images),
            "style_reference_count": len(reference_images),
            "product_reference_count": 0,
            "concurrency": options.concurrency,
            "upload_gate_enabled": upload_gate is not None,
            "upload_gate_reference_threshold": STYLE_REPLICATE2_UPLOAD_GATE_REFERENCE_THRESHOLD,
            "upload_concurrency_limit": (
                STYLE_REPLICATE2_UPLOAD_CONCURRENCY_LIMIT
                if upload_gate is not None
                else None
            ),
            "renders": manifest,
        }
        summary_path = json_dir / "summary.json"
        write_json(summary_path, summary)
        run_logger.log(f"复刻风格图片2任务完成：{summary_path}")

        record = {
            **history_base,
            "status": "completed",
            "summary_file": str(summary_path),
            "render_manifest_file": summary["render_manifest_file"],
            "debug_log_file": summary["debug_log_file"],
            "reference_source": reference_meta[0] if reference_meta else {},
            "reference_sources": reference_meta,
            "style_source": reference_meta[0] if reference_meta else {},
            "style_sources": reference_meta,
            "product_source": {},
            "product_sources": [],
            "rendered_image_count": summary["rendered_image_count"],
            "image_key_slot": image_api_selection["key_slot"],
            "latest_images": [
                image_path
                for item in manifest
                for image_path in item.get("images", [])
            ][:8],
        }
        context.append_history(record)
        return record
    except Exception as exc:
        logger.log(f"复刻风格图片2任务失败：{exc}")
        cleanup_failed_run_dir(context, run_dir)
        raise


def open_path(path: Path) -> None:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise AppError(f"路径不存在：{resolved}")
    if os.name == "nt":
        os.startfile(str(resolved))
        return
    if sys.platform == "darwin":
        subprocess.run(["open", str(resolved)], check=False)
        return
    subprocess.run(["xdg-open", str(resolved)], check=False)

