from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def detect_project_root(start_file: Path) -> Path:
    """
    Detect repo root by walking upwards from a file path until we find a typical repo layout.

    We require:
      - cli/ directory
      - roles/ directory
      - group_vars/ directory

    This avoids brittle parents[N] assumptions and fixes "cli/cli/..." path bugs.
    """
    here = start_file.resolve()
    for p in [here, *here.parents]:
        if (
            (p / "cli").is_dir()
            and (p / "roles").is_dir()
            and (p / "group_vars").is_dir()
        ):
            return p
    raise SystemExit(f"Could not detect project root from: {here}")


def build_env_with_project_root(project_root: Path) -> dict[str, str]:
    """
    Return an environment dict where PYTHONPATH includes the project root.
    This makes `utils` and other top-level packages importable in subprocesses.
    """
    env = os.environ.copy()
    root_str = str(project_root)
    existing = env.get("PYTHONPATH")
    if existing:
        parts = existing.split(os.pathsep)
        if root_str not in parts:
            env["PYTHONPATH"] = root_str + os.pathsep + existing
    else:
        env["PYTHONPATH"] = root_str
    return env
