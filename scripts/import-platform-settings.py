from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform_backend.app.database import init_db  # noqa: E402
from platform_backend.app.settings_service import save_global_settings  # noqa: E402


def _read_export(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"settings export not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("settings export must be a JSON object")
    if payload.get("schema_version") != 1:
        raise SystemExit("unsupported settings export schema_version")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Import exported platform settings.")
    parser.add_argument("path", help="Path to platform-settings-export.json")
    args = parser.parse_args()

    payload = _read_export(Path(args.path).resolve())
    settings = payload.get("settings") or {}
    secrets = payload.get("secrets") or {}
    if not isinstance(settings, dict) or not isinstance(secrets, dict):
        raise SystemExit("settings and secrets must be JSON objects")

    init_db()
    normalized = save_global_settings({**settings, **secrets}, actor_id=None)
    secret_count = sum(1 for value in secrets.values() if value)
    print("Imported platform settings.")
    print(f"Settings keys: {len(settings)}")
    print(f"Default admin secrets: {secret_count}")
    print(f"Effective image_model: {normalized.get('image_model')}")
    print(f"Effective 1K model: {normalized.get('image_model_gpt_image_2_1k')}")


if __name__ == "__main__":
    main()
