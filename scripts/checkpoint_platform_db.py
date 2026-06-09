from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def checkpoint_database(path: Path) -> None:
    if not path.exists():
        return
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Checkpoint a platform SQLite database before packaging.")
    parser.add_argument("path", nargs="?", default="platform_runtime/platform.db")
    args = parser.parse_args()
    checkpoint_database(Path(args.path))


if __name__ == "__main__":
    main()
