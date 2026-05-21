from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import CONFIG
from .security import hash_password, utc_now


def connect() -> sqlite3.Connection:
    CONFIG.ensure_dirs()
    conn = sqlite3.connect(CONFIG.database_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def json_loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(str(value))
    except Exception:
        return default


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def init_db() -> None:
    CONFIG.ensure_dirs()
    schema_path = Path(__file__).with_name("schema.sql")
    with connect() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
    bootstrap_admin()


def bootstrap_admin() -> None:
    with transaction() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (CONFIG.bootstrap_admin_username,),
        ).fetchone()
        if existing:
            return
        user_id = new_id("usr")
        now = utc_now()
        conn.execute(
            """
            INSERT INTO users (
                id, username, display_name, password_hash, role, status,
                must_change_password, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'admin', 'active', 1, ?, ?)
            """,
            (
                user_id,
                CONFIG.bootstrap_admin_username,
                "系统管理员",
                hash_password(CONFIG.bootstrap_admin_password),
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO user_quotas (
                user_id, balance, daily_limit, monthly_limit, concurrent_limit,
                storage_limit_mb, created_at, updated_at
            )
            VALUES (?, 0, 0, 0, 3, 20480, ?, ?)
            """,
            (user_id, now, now),
        )

