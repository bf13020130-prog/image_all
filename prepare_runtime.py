#!/usr/bin/env python3
from __future__ import annotations

import importlib.metadata as metadata
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT_DISTRIBUTIONS = (
    "fastapi",
    "Pillow",
    "python-multipart",
    "requests",
    "uvicorn",
)


def project_root() -> Path:
    return Path(__file__).resolve().parent


def copy_tree(source: Path, target: Path, *, ignore: Any = None) -> None:
    shutil.copytree(
        source,
        target,
        ignore=ignore,
        dirs_exist_ok=True,
    )


def runtime_ignore(base: Path, *, strip_site_packages: bool = False):
    def inner(current_dir: str, names: list[str]) -> set[str]:
        ignored = set()
        relative = Path(current_dir).resolve().relative_to(base.resolve())
        relative_text = relative.as_posix()

        common = {"__pycache__"}
        ignored.update(common.intersection(names))

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
    if not match:
        return None
    return match.group(1)


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


def copy_required_site_packages(source_root: Path, target_root: Path) -> None:
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
                copy_tree(source_path, target_site_packages / relative_dir, ignore=runtime_ignore(source_path))
                continue
            if not source_path.is_file():
                continue
            if source_path.suffix.lower() in {".pyc", ".pyo", ".log"}:
                continue
            try:
                relative_path = source_path.relative_to(distribution_root)
            except ValueError:
                continue
            target_path = target_site_packages / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)


def update_package_json(
    root: Path,
    *,
    python_target: Path,
    backend_target: Path,
) -> None:
    package_path = root / "package.json"
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    extra_resources = payload.setdefault("build", {}).setdefault("extraResources", [])

    resource_paths = {
        "backend": str(backend_target.relative_to(root)).replace("\\", "/"),
        "python-runtime": str(python_target.relative_to(root)).replace("\\", "/"),
    }
    for item in extra_resources:
        target_name = item.get("to")
        if target_name in resource_paths:
            item["from"] = resource_paths[target_name]

    package_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def cleanup_old_build_dirs(
    runtime_root: Path,
    *,
    python_target: Path,
    backend_target: Path,
) -> None:
    for pattern, active_path in (
        ("python-runtime-build-*", python_target),
        ("backend-build-*", backend_target),
    ):
        for candidate in runtime_root.glob(pattern):
            if candidate == active_path:
                continue
            shutil.rmtree(candidate, ignore_errors=True)


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
    for item in source_root.iterdir():
        if not item.is_file():
            continue
        if item.name.lower() in {name.lower() for name in allow_names}:
            shutil.copy2(item, target_root / item.name)


def main() -> int:
    root = project_root()
    runtime_root = root / "runtime"
    python_target = runtime_root / "python-runtime"
    backend_target = runtime_root / "backend"
    source_python_root = Path(sys.base_prefix).resolve()

    runtime_root.mkdir(parents=True, exist_ok=True)
    for target in (python_target, backend_target):
        if target.exists():
            shutil.rmtree(target)
    python_target.mkdir(parents=True, exist_ok=True)

    copy_root_files(source_python_root, python_target)
    for directory_name in ("DLLs", "Lib", "tcl"):
        source_dir = source_python_root / directory_name
        if source_dir.exists():
            copy_tree(
                source_dir,
                python_target / directory_name,
                ignore=runtime_ignore(
                    source_dir,
                    strip_site_packages=directory_name == "Lib",
                ),
            )
    copy_required_site_packages(source_python_root, python_target)

    for path in python_target.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo", ".log"}:
            try:
                path.unlink()
            except OSError:
                continue

    backend_target.mkdir(parents=True, exist_ok=True)
    for file_name in (
        "app.py",
        "api_server.py",
        "backend_main.py",
        "pipeline_core.py",
        "legacy_tk_app.py",
    ):
        shutil.copy2(root / file_name, backend_target / file_name)

    seed_source = root / "config.json"
    if not seed_source.exists():
        seed_source = root / "config.example.json"
    shutil.copy2(seed_source, runtime_root / "seed-config.json")

    update_package_json(
        root,
        python_target=python_target,
        backend_target=backend_target,
    )
    cleanup_old_build_dirs(
        runtime_root,
        python_target=python_target,
        backend_target=backend_target,
    )

    for stale_dir in (runtime_root / "python-runtime-slim", runtime_root / "python-runtime-stage", runtime_root / "backend-stage", runtime_root / "win-unpacked"):
        shutil.rmtree(stale_dir, ignore_errors=True)
    for stale_file in runtime_root.glob("builder-*.yml"):
        stale_file.unlink(missing_ok=True)

    print(f"python runtime prepared: {python_target}")
    print(f"backend sources prepared: {backend_target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
