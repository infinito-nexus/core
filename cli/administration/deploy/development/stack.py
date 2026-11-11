from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

STACK_KEY = "INFINITO_STACK_NAME"
COMPOSE_KEY = "COMPOSE_PROJECT_NAME"

_PROJECT_CHAR = re.compile(r"[a-z0-9_-]")


def normalize(raw: str) -> str:
    """Return ``raw`` as compose turns a directory name into a project name.

    Mirrors compose-go's ``NormalizeProjectName``; a drift renames the
    implicit project and orphans every running stack with its volumes.

    Args:
        raw: directory basename.
    """
    return "".join(_PROJECT_CHAR.findall(raw.lower())).lstrip("_-")


def _project_dir_name(repo_root: Path, environ: Mapping[str, str]) -> str:
    """Basename of the directory compose resolves as its working directory.

    Go's ``os.Getwd`` returns ``$PWD`` when it names the same directory, so a
    checkout reached through a symlink keeps the symlink's name.

    Args:
        repo_root: directory compose runs in.
        environ: environment compose inherits.
    """
    pwd = environ.get("PWD") or ""
    try:
        same = pwd.startswith("/") and Path(pwd).samefile(repo_root)
    except OSError:
        same = False
    return Path(pwd).name if same else repo_root.name


def stack_name(repo_root: Path, environ: Mapping[str, str]) -> str:
    """Return the compose project every call of this checkout addresses.

    Args:
        repo_root: checkout whose compose files the stack runs from.
        environ: environment holding INFINITO_STACK_NAME and COMPOSE_PROJECT_NAME.

    Returns:
        INFINITO_STACK_NAME when set, else the name compose derives on its own.

    Raises:
        SystemExit: INFINITO_STACK_NAME is not a valid compose project name.
    """
    explicit = (environ.get(STACK_KEY) or "").strip()
    if explicit:
        if normalize(explicit) != explicit:
            raise SystemExit(
                f"{STACK_KEY}={explicit!r} is not a valid compose project name: "
                "use lowercase letters, digits, '_' and '-', starting with a "
                "letter or digit."
            )
        return explicit
    implicit = (environ.get(COMPOSE_KEY) or "").strip()
    return implicit or normalize(_project_dir_name(repo_root, environ))


def compose_argv(repo_root: Path) -> list[str]:
    """Return ``docker compose`` with the stack's ``-p`` and ``-f`` flags.

    Args:
        repo_root: checkout the call runs in.
    """
    from .env import compose_file_args

    return [
        "docker",
        "compose",
        "-p",
        stack_name(repo_root, os.environ),
        *compose_file_args(),
    ]


if __name__ == "__main__":
    from . import PROJECT_ROOT

    print("\n".join(compose_argv(PROJECT_ROOT)[2:]))
