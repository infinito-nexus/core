from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]


def detect_runtime() -> str:
    """
    Detect the current execution runtime.

    Returns the value of the ``RUNTIME`` env var when set (callers pass
    e.g. ``"dev"`` here to flag a local development compose run), or one
    of the auto-detected labels otherwise:

      - "act"    : local GitHub Actions emulation (act)
      - "github" : real GitHub Actions runner
      - "host"   : native host execution (default)

    Precedence:
      1) RUNTIME (explicit override)
      2) act (must come before github because act sets GITHUB_ACTIONS=true)
      3) github
      4) host
    """
    # 1) explicit override wins
    v = (os.getenv("RUNTIME") or "").strip()
    if v:
        return v

    # 2) act (must be before GitHub)
    if os.getenv("ACT") == "true" or os.getenv("ACT_RUNNER"):
        return "act"

    # 3) GitHub Actions
    if (
        os.getenv("GITHUB_ACTIONS") == "true"
        or os.getenv("INFINITO_RUNNING_ON_GITHUB") == "true"
    ):
        return "github"

    # 4) default
    return "host"
