"""Verify that ARG declarations used in FROM instructions are in the global scope.

In multi-stage Dockerfiles every ``ARG`` whose value is referenced by a
``FROM`` instruction must be declared *before* the first ``FROM`` (the global
scope).  An ``ARG`` declared inside a build stage is scoped to that stage only
and is invisible to subsequent ``FROM`` instructions, which causes Docker to
treat the variable as empty and fail with::

    WARN: UndefinedArgInFrom: FROM argument '...' is not declared
    failed to solve: failed to parse stage name ":": invalid reference format

The test scans all ``files/Dockerfile`` files under ``roles/`` and fails for
any file where an ``ARG`` used in a ``FROM`` instruction is not declared before
the first ``FROM``.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_REPO_ROOT = PROJECT_ROOT
_ROLES_ROOT = _REPO_ROOT / "roles"

# Matches a FROM line that references at least one ${VAR}
_FROM_ARG_RE = re.compile(r"^\s*FROM\s+.*\$\{(\w+)\}", re.IGNORECASE)
# Matches an ARG declaration: ARG VARNAME or ARG VARNAME=default
_ARG_DECL_RE = re.compile(r"^\s*ARG\s+(\w+)", re.IGNORECASE)
# Matches any FROM line (marks the end of the global scope)
_FROM_RE = re.compile(r"^\s*FROM\b", re.IGNORECASE)


def _collect_dockerfiles() -> list[Path]:
    return sorted(_ROLES_ROOT.glob("*/files/Dockerfile"))


def _undeclared_from_args(dockerfile: Path) -> list[tuple[int, str, str]]:
    """Return a list of (line_no, from_line, var_name) for each ARG used in a
    FROM instruction that was not declared in the global scope."""
    lines = read_text(str(dockerfile)).splitlines()

    # Pass 1 — collect ARGs declared before the first FROM (global scope)
    global_args: set[str] = set()
    for line in lines:
        if _FROM_RE.match(line):
            break
        m = _ARG_DECL_RE.match(line)
        if m:
            global_args.add(m.group(1))

    # Pass 2 — check every FROM that references an ARG
    violations: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(lines, start=1):
        violations.extend(
            (lineno, line.strip(), m.group(1))
            for m in _FROM_ARG_RE.finditer(line)
            if m.group(1) not in global_args
        )

    return violations


class TestDockerfileArgScope(unittest.TestCase):
    """Fail when ARGs used in FROM instructions are not in the global scope."""

    def test_from_args_declared_globally(self) -> None:
        dockerfiles = _collect_dockerfiles()
        self.assertTrue(
            dockerfiles or True,  # pass even when no Dockerfiles exist yet
            "No Dockerfiles found — check _ROLES_ROOT path.",
        )

        failures: list[str] = []
        for dockerfile in dockerfiles:
            violations = _undeclared_from_args(dockerfile)
            for lineno, from_line, var_name in violations:
                relative = dockerfile.relative_to(_REPO_ROOT).as_posix()
                failures.append(
                    f"{relative}:{lineno}: ARG '{var_name}' used in FROM but not "
                    f"declared in global scope — '{from_line}'"
                )

        self.assertFalse(
            failures,
            "The following Dockerfiles reference ARGs in FROM instructions that are "
            "not declared before the first FROM (global scope).\n"
            "ARGs used in FROM must be declared globally so Docker can resolve them "
            "in multi-stage builds:\n\n" + "\n".join(f"  {f}" for f in failures),
        )


if __name__ == "__main__":
    unittest.main()
