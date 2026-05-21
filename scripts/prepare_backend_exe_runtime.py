#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_EXE_NAME = "design_output_backend.exe"


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def run_pyinstaller(*, dist_path: Path, work_path: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(ROOT / "design_output_backend.spec"),
        "--distpath",
        str(dist_path),
        "--workpath",
        str(work_path),
    ]
    subprocess.run(command, cwd=ROOT, check=True)


def copy_backend_exe(source_root: Path) -> Path:
    source_dir = source_root / "design_output_backend"
    source_exe = source_dir / BACKEND_EXE_NAME
    if not source_exe.exists():
        raise FileNotFoundError(f"PyInstaller output not found: {source_exe}")

    target_dir = ROOT / "runtime" / "backend-exe"
    remove_path(target_dir)
    shutil.copytree(source_dir, target_dir)
    return target_dir / BACKEND_EXE_NAME


def main() -> int:
    temp_root = ROOT / f"_tmp_backend_exe_{uuid.uuid4().hex[:8]}"
    dist_path = temp_root / "dist"
    work_path = temp_root / "build"

    try:
        run_pyinstaller(dist_path=dist_path, work_path=work_path)
        target_exe = copy_backend_exe(dist_path)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    print(f"backend exe prepared: {target_exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
