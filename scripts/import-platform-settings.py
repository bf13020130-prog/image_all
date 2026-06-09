from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform_backend.app.database import connect, init_db  # noqa: E402
from platform_backend.app.settings_service import (  # noqa: E402
    save_global_settings,
    save_user_secrets,
    save_user_settings,
)


def _read_export(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"settings export not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("settings export must be a JSON object")
    if payload.get("schema_version") != 1:
        raise SystemExit("unsupported settings export schema_version")
    return payload


def _parse_usernames(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _target_users(*, mode: str, usernames: list[str]) -> list[dict[str, str]]:
    if mode == "none" and not usernames:
        return []
    with connect() as conn:
        if usernames:
            placeholders = ",".join("?" for _ in usernames)
            rows = conn.execute(
                f"""
                SELECT id, username, role, status
                FROM users
                WHERE username IN ({placeholders})
                ORDER BY username
                """,
                usernames,
            ).fetchall()
        elif mode == "active":
            rows = conn.execute(
                """
                SELECT id, username, role, status
                FROM users
                WHERE status = 'active'
                ORDER BY username
                """
            ).fetchall()
        elif mode == "all":
            rows = conn.execute(
                """
                SELECT id, username, role, status
                FROM users
                ORDER BY username
                """
            ).fetchall()
        else:
            rows = []
    return [
        {
            "id": str(row["id"]),
            "username": str(row["username"]),
            "role": str(row["role"]),
            "status": str(row["status"]),
        }
        for row in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Import exported platform settings.")
    parser.add_argument("path", help="Path to platform-settings-export.json")
    parser.add_argument(
        "--apply-to-users",
        choices=("none", "active", "all"),
        default="none",
        help="Also copy imported settings and secrets into existing server users.",
    )
    parser.add_argument(
        "--target-usernames",
        default="",
        help="Comma-separated usernames to update. Overrides --apply-to-users selection.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print target users without writing settings.",
    )
    args = parser.parse_args()

    payload = _read_export(Path(args.path).resolve())
    settings = payload.get("settings") or {}
    secrets = payload.get("secrets") or {}
    if not isinstance(settings, dict) or not isinstance(secrets, dict):
        raise SystemExit("settings and secrets must be JSON objects")

    init_db()
    usernames = _parse_usernames(args.target_usernames)
    targets = _target_users(mode=args.apply_to_users, usernames=usernames)
    if usernames:
        found_usernames = {item["username"] for item in targets}
        missing_usernames = [
            username for username in usernames if username not in found_usernames
        ]
        if missing_usernames:
            raise SystemExit(
                "target users not found: " + ", ".join(missing_usernames)
            )
    if args.dry_run:
        print("Dry run; no settings were imported.")
        print(f"Target users: {', '.join(item['username'] for item in targets) or '(none)'}")
        print(f"Settings keys: {len(settings)}")
        print(f"Secrets keys: {len(secrets)}")
        return

    normalized = save_global_settings({**settings, **secrets}, actor_id=None)
    for target in targets:
        save_user_settings(target["id"], settings)
        save_user_secrets(target["id"], secrets)
    secret_count = sum(1 for value in secrets.values() if value)
    print("Imported platform settings.")
    print(f"Settings keys: {len(settings)}")
    print(f"Default admin secrets: {secret_count}")
    print(f"Users updated: {len(targets)}")
    if targets:
        print(f"Target users: {', '.join(item['username'] for item in targets)}")
    print(f"Effective image_model: {normalized.get('image_model')}")
    print(f"Effective 1K model: {normalized.get('image_model_gpt_image_2_1k')}")


if __name__ == "__main__":
    main()
