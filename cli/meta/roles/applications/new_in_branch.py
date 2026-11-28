"""Print application roles new on this branch (in its Git tree, staged or untracked but not ignored, and absent under roles/ at a ref, default origin/main); empty when the ref is unresolvable."""

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


def roles_on_branch(roles_dir: Path) -> set[str] | None:
    """
    Args:
        roles_dir: the ``roles/`` directory of the checkout.

    Returns:
        names of the roles whose ``vars/main.yml`` Git tracks or would track
        (untracked and not ignored), so a role a pull or the skeleton samples
        place under an ignored path is no part of the branch; ``None`` when
        Git cannot list the files.
    """
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(roles_dir.parent),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                f":(glob)roles/*/{ROLE_FILE_VARS_MAIN}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return {rel.split("/")[1] for rel in out.stdout.split("\0") if rel}


def _declares_application_id(role_dir: Path) -> bool:
    vars_file = role_dir / ROLE_FILE_VARS_MAIN
    try:
        return bool(_APPLICATION_ID_RE.search(read_text(str(vars_file))))
    except OSError:
        return False


def new_application_roles(roles_dir: Path, ref: str = "origin/main") -> list[str]:
    present = roles_present_in_ref(roles_dir, ref)
    branch = roles_on_branch(roles_dir)
    if present is None or branch is None:
        return []
    return sorted(
        name for name in branch - present if _declares_application_id(roles_dir / name)
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    ref = args[0] if args else "origin/main"
    print(" ".join(new_application_roles(Path("roles"), ref)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
