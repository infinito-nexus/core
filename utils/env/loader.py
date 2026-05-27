"""Idempotent ``.env`` loader for Python CLI entry-points."""

from __future__ import annotations

import os
from pathlib import Path

from utils.env.parser import parse_static_env

_LOADED_FLAG = "INFINITO_ENV_LOADED"  # nocheck: env-loader-internal-guard
_DOTENV_NAME = ".env"


def _find_dotenv(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        path = candidate / _DOTENV_NAME
        if path.is_file():
            return path
    return None


def load_dotenv_once(start: Path | None = None) -> Path | None:
    """Source ``.env`` into ``os.environ`` exactly once per process.

    Mirrors the bash ``scripts/meta/env/load.sh`` semantics:

    * Honours ``INFINITO_ENV_LOADED=1`` and returns immediately when set.
    * Caller-set values win over ``.env`` defaults (``setdefault``).
    * Walks up from ``start`` (default: current working directory) until a
      ``.env`` is found; returns ``None`` if none exists in any parent.
    """
    if os.environ.get(_LOADED_FLAG) == "1":
        return None

    dotenv = _find_dotenv((start or Path.cwd()).resolve())
    if dotenv is None:
        return None

    for key, value in parse_static_env(dotenv).items():
        os.environ.setdefault(key, value)

    os.environ[_LOADED_FLAG] = "1"
    return dotenv
