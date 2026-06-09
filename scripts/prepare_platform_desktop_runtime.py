#!/usr/bin/env python3
from __future__ import annotations

import importlib.metadata as metadata
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    from checkpoint_platform_db import checkpoint_database
except ModuleNotFoundError:
    from scripts.checkpoint_platform_db import checkpoint_database


ROOT_DISTRIBUTIONS = (
    "cryptography",
    "fastapi",
    "Pillow",
    "pydantic",
    "python-multipart",
    "requests",
    "uvicorn",
)

USE_EXAMPLE_CONFIG_SEED_ENV = "PLATFORM_USE_EXAMPLE_CONFIG_SEED"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def seed_config_source(root: Path) -> Path:
    example_source = root / "config.example.json"
    live_source = root / "platform_runtime" / "config.json"
    local_source = root / "config.json"
    if os.environ.get(USE_EXAMPLE_CONFIG_SEED_ENV) == "1":
        if not example_source.exists():
            raise FileNotFoundError(f"seed config template not found: {example_source}")
        return example_source
    if live_source.exists():
        return live_source
    if local_source.exists():
        return local_source
    if not example_source.exists():
        raise FileNotFoundError(f"seed config template not found: {example_source}")
    return example_source


def copy_tree(source: Path, target: Path, *, ignore: Any = None) -> None:
    shutil.copytree(source, target, ignore=ignore, dirs_exist_ok=True)


def runtime_ignore(base: Path, *, strip_site_packages: bool = False):
    def inner(current_dir: str, names: list[str]) -> set[str]:
        ignored = {"__pycache__"}.intersection(names)
        relative = Path(current_dir).resolve().relative_to(base.resolve())
        relative_text = relative.as_posix()

        if relative_text == ".":
            for name in names:
                lower = name.lower()
                if lower in {"doc", "docs", "include", "libs", "scripts", "tools"}:
                    ignored.add(name)
                if strip_site_packages and lower == "site-packages":
                    ignored.add(name)
                if lower.endswith(".chm") or lower.endswith(".zip"):
                    ignored.add(name)
        if relative_text == "." and base.name == "site-packages":
            for name in names:
                lower = name.lower()
                if (
                    lower.startswith("pip")
                    or lower.startswith("setuptools")
                    or lower.startswith("wheel")
                    or lower.startswith("pyinstaller")
                    or lower.startswith("pyinstaller_hooks_contrib")
                    or lower.startswith("pkg_resources")
                    or lower.startswith("build")
                    or lower.startswith("installer")
                ):
                    ignored.add(name)
        if relative_text == "." and base.name == "Lib":
            for name in names:
                lower = name.lower()
                if lower in {
                    "ensurepip",
                    "idlelib",
                    "lib2to3",
                    "pydoc_data",
                    "test",
                    "turtledemo",
                    "venv",
                }:
                    ignored.add(name)
        return ignored

    return inner


def normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement_name(requirement: str) -> str | None:
    match = re.match(r"^\s*([A-Za-z0-9_.-]+)", requirement)
    return match.group(1) if match else None


def resolve_required_distributions() -> list[str]:
    available = {
        normalize_distribution_name(dist.metadata["Name"]): dist.metadata["Name"]
        for dist in metadata.distributions()
        if dist.metadata["Name"]
    }
    queue = list(ROOT_DISTRIBUTIONS)
    resolved: list[str] = []
    seen: set[str] = set()

    while queue:
        raw_name = queue.pop(0)
        canonical_name = available.get(normalize_distribution_name(raw_name))
        if canonical_name is None or canonical_name in seen:
            continue
        seen.add(canonical_name)
        resolved.append(canonical_name)
        for requirement in metadata.distribution(canonical_name).requires or []:
            dependency_name = parse_requirement_name(requirement)
            if dependency_name:
                queue.append(dependency_name)

    return sorted(resolved)


def copy_required_site_packages(target_root: Path) -> None:
    target_site_packages = target_root / "Lib" / "site-packages"
    target_site_packages.mkdir(parents=True, exist_ok=True)

    for distribution_name in resolve_required_distributions():
        distribution = metadata.distribution(distribution_name)
        distribution_root = Path(distribution.locate_file("")).resolve()
        for package_file in distribution.files or []:
            source_path = Path(distribution.locate_file(package_file)).resolve()
            if source_path.is_dir():
                try:
                    relative_dir = source_path.relative_to(distribution_root)
                except ValueError:
                    continue
                copy_tree(
                    source_path,
                    target_site_packages / relative_dir,
                    ignore=runtime_ignore(source_path),
                )
                continue
            if not source_path.is_file() or source_path.suffix.lower() in {".pyc", ".pyo", ".log"}:
                continue
            try:
                relative_path = source_path.relative_to(distribution_root)
            except ValueError:
                continue
            target_path = target_site_packages / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)


def copy_root_files(source_root: Path, target_root: Path) -> None:
    target_root.mkdir(parents=True, exist_ok=True)
    allow_names = {
        "python.exe",
        "pythonw.exe",
        "python3.dll",
        "python312.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "LICENSE.txt",
    }
    allowed_lower = {name.lower() for name in allow_names}
    for item in source_root.iterdir():
        if item.is_file() and item.name.lower() in allowed_lower:
            shutil.copy2(item, target_root / item.name)


def prepare_python_runtime(root: Path, target: Path) -> None:
    source_python_root = Path(sys.base_prefix).resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    copy_root_files(source_python_root, target)
    for directory_name in ("DLLs", "Lib", "tcl"):
        source_dir = source_python_root / directory_name
        if source_dir.exists():
            copy_tree(
                source_dir,
                target / directory_name,
                ignore=runtime_ignore(
                    source_dir,
                    strip_site_packages=directory_name == "Lib",
                ),
            )
    copy_required_site_packages(target)
    for path in target.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo", ".log"}:
            path.unlink(missing_ok=True)


def prepare_backend(root: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    for directory_name in ("platform_backend", "platform_frontend"):
        copy_tree(root / directory_name, target / directory_name)
    for file_name in (
        "config.example.json",
        "pipeline_core.py",
    ):
        shutil.copy2(root / file_name, target / file_name)
    env_path = root / ".env"
    if env_path.exists():
        shutil.copy2(env_path, target / ".env")


def prepare_seed_config(root: Path, runtime_root: Path) -> None:
    source = seed_config_source(root)
    shutil.copy2(source, runtime_root / "platform-seed-config.json")


def prepare_seed_database(root: Path, runtime_root: Path) -> None:
    database_root = root / "platform_runtime"
    checkpoint_database(database_root / "platform.db")
    copied_names: set[str] = set()
    for source_name, target_name in (
        ("platform.db", "platform-seed.db"),
        ("platform.db-wal", "platform-seed.db-wal"),
        ("platform.db-shm", "platform-seed.db-shm"),
    ):
        source = database_root / source_name
        if source.exists():
            shutil.copy2(source, runtime_root / target_name)
            copied_names.add(target_name)
    for target_name in ("platform-seed.db-wal", "platform-seed.db-shm"):
        if "platform-seed.db" in copied_names and target_name not in copied_names:
            (runtime_root / target_name).write_bytes(b"")


def main() -> int:
    root = project_root()
    runtime_root = root / "runtime-platform"
    python_target = runtime_root / "python-runtime"
    backend_target = runtime_root / "backend"
    runtime_root.mkdir(parents=True, exist_ok=True)

    prepare_python_runtime(root, python_target)
    prepare_backend(root, backend_target)
    prepare_seed_config(root, runtime_root)
    prepare_seed_database(root, runtime_root)

    print(f"platform python runtime prepared: {python_target}")
    print(f"platform backend prepared: {backend_target}")
    print(f"platform seed config prepared: {runtime_root / 'platform-seed-config.json'}")
    print(f"platform seed config source: {seed_config_source(root)}")
    print(f"platform seed database source: {root / 'platform_runtime' / 'platform.db'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
