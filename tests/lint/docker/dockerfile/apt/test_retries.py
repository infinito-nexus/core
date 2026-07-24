"""Every Dockerfile ``RUN`` calling ``apt-get update``/``install`` must pass
``Acquire::Retries`` so a transient mirror fetch retries instead of aborting the
build with exit 100 (``dnf`` retries by default, ``apk`` has no flag)."""

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

_J2_CTRL_RE = re.compile(r"\{%-?.*?-?%\}", re.DOTALL)
_RUN_START_RE = re.compile(r"^\s*RUN\b", re.IGNORECASE)
_APT_CMD_RE = re.compile(
    r"\bapt-get\b(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+(?:update|install)\b",
    re.IGNORECASE,
)
_RETRIES_RE = re.compile(r"Acquire::Retries", re.IGNORECASE)


def _collect_dockerfiles() -> list[Path]:
    paths: set[Path] = set()
    paths.update(_ROLES_ROOT.glob("*/files/Dockerfile"))
    paths.update(_ROLES_ROOT.glob("*/files/**/Dockerfile"))
    paths.update(_ROLES_ROOT.glob("*/templates/Dockerfile*.j2"))
    return sorted(paths)


def _iter_run_blocks(source: str):
    cleaned = _J2_CTRL_RE.sub("", source)
    lines = cleaned.splitlines()
    i = 0
    while i < len(lines):
        if not _RUN_START_RE.match(lines[i]):
            i += 1
            continue
        start = i + 1
        buf = [lines[i]]
        while lines[i].rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            buf.append(lines[i])
        yield start, "\n".join(buf)
        i += 1


def _violations(dockerfile: Path) -> list[str]:
    relative = dockerfile.relative_to(_REPO_ROOT).as_posix()
    failures: list[str] = []
    source = read_text(str(dockerfile))
    for lineno, block in _iter_run_blocks(source):
        if not _APT_CMD_RE.search(block):
            continue
        if _RETRIES_RE.search(block):
            continue
        failures.append(
            f"{relative}:{lineno}: RUN calls `apt-get update`/`install` "
            "without `Acquire::Retries`. A transient mirror fetch aborts the "
            "build with exit 100. Add `-o Acquire::Retries=3` to the apt-get "
            "call (or write it to apt.conf in the same RUN)."
        )
    return failures


class TestDockerfileAptRetries(unittest.TestCase):
    def test_apt_calls_set_acquire_retries(self) -> None:
        self.assertTrue(
            _ROLES_ROOT.is_dir(),
            f"'roles' directory not found at: {_ROLES_ROOT}",
        )

        failures: list[str] = []
        for path in _collect_dockerfiles():
            failures.extend(_violations(path))

        self.assertFalse(
            failures,
            "Dockerfile apt-get retry-hardening contract violated:\n\n"
            + "\n".join(f"  {f}" for f in failures),
        )


if __name__ == "__main__":
    unittest.main()
