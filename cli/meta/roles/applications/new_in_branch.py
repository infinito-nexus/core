"""Print application roles new on this branch (absent under roles/ at a ref, default origin/main); empty when the ref is unresolvable."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

_APPLICATION_ID_RE = re.compile(r"(?m)^application_id:[ \t]*(?!#)(\S.*)$")


def roles_present_in_ref(roles_dir: Path, ref: str) -> set[str] | None:
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(roles_dir.parent),
                "ls-tree",
                "-d",
                "--name-only",
                f"{ref}:roles",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def _declares_application_id(role_dir: Path) -> bool:
    vars_file = role_dir / ROLE_FILE_VARS_MAIN
    try:
        return bool(_APPLICATION_ID_RE.search(read_text(str(vars_file))))
    except OSError:
        return False


def new_application_roles(roles_dir: Path, ref: str = "origin/main") -> list[str]:
    present = roles_present_in_ref(roles_dir, ref)
    if present is None:
        return []
    return sorted(
        role_dir.name
        for role_dir in roles_dir.iterdir()
        if role_dir.is_dir()
        and role_dir.name not in present
        and _declares_application_id(role_dir)
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    ref = args[0] if args else "origin/main"
    print(" ".join(new_application_roles(Path("roles"), ref)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
