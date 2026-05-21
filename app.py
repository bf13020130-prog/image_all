#!/usr/bin/env python3
from __future__ import annotations

from pipeline_core import *  # noqa: F403 - public compatibility facade for api_server.py.


def main() -> int:
    from legacy_tk_app import main as legacy_main

    return legacy_main()


def __getattr__(name: str):
    if name == "GeneratorApp":
        from legacy_tk_app import GeneratorApp

        return GeneratorApp
    raise AttributeError(name)


if __name__ == "__main__":
    raise SystemExit(main())
