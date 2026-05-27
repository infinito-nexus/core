from __future__ import annotations

import subprocess
import sys


def run(
    cmd: list[str],
    *,
    cwd: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """
    Run a command with stdout/stderr passthrough.

    Note: Many repo commands (e.g. `make`) must run in the repo root so the Makefile is found.
    """
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def run_make(repo_root: str, *targets: str) -> None:
    """
    Run `make <targets...>` from the repo root.

    This prevents errors like:
      make: *** No rule to make target 'clean'.  Stop.
    """
    final_targets = targets or ("help",)
    run(["make", *final_targets], cwd=repo_root, check=True)
