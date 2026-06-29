"""Verify that every Dockerfile ``RUN`` that calls ``apt-get update`` purges
stale apt lists first and does NOT bypass the ``Valid-Until`` check.

Two contracts are enforced.

1. Every ``RUN`` that contains ``apt-get update`` MUST also contain
   ``rm -rf /var/lib/apt/lists/*`` **before** the ``apt-get update`` call
   in the same ``RUN`` block.

   Reason: Debian/Ubuntu base images ship pre-baked ``/var/lib/apt/lists/*``
   files whose embedded ``Valid-Until`` field can expire (the ``-updates`` /
   ``-security`` Release files are regenerated every few days). When
   ``apt-get update`` runs on top of a stale baked list it errors with::

       E: Release file for ...trixie-updates/InRelease is expired
       E: Release file for ...trixie-security/InRelease is expired

   and the build layer aborts with exit 100. Purging the cached lists
   *before* ``apt-get update`` forces apt to re-fetch fresh, in-window
   ``InRelease`` files from the configured source. A trailing
   ``&& rm -rf /var/lib/apt/lists/*`` (image-hygiene only) does NOT
   satisfy this contract — by the time it would run, the failing
   ``apt-get update`` has already aborted the RUN.

2. No ``RUN`` MAY pass ``-o Acquire::Check-Valid-Until=false`` (or any
   spelling such as ``=0`` / ``=no``) to ``apt-get``.

   Reason: that flag disables apt's replay-protection check on the signed
   ``Valid-Until`` field. The right cure for a stale list is to refresh
   it (contract 1), not to silence the signed-expiry check.

Scope: every Dockerfile under ``roles/*/files/`` (any depth) and every
``Dockerfile*.j2`` under ``roles/*/templates/``. Alpine (``apk``),
Yum/DNF, Pacman and language package managers are out of scope — they
use a different metadata model and have not exhibited this failure
class in this repo.
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

# Strip Jinja2 control tags so they don't fragment RUN-block parsing in
# templated Dockerfiles. Any branch that ships an unsafe RUN must fail
# the lint, so collapsing the branches into one text body is correct.
_J2_CTRL_RE = re.compile(r"\{%-?.*?-?%\}", re.DOTALL)

_RUN_START_RE = re.compile(r"^\s*RUN\b", re.IGNORECASE)
# `apt-get update` with optional `-flag` / `--flag` / `-o KEY=VAL` tokens
# in between, but not arbitrary words (so `apt-get install update` does
# NOT match).
_APT_UPDATE_RE = re.compile(
    r"\bapt-get\b(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+update\b",
    re.IGNORECASE,
)
_RM_LISTS_RE = re.compile(r"\brm\s+-[rRfv]*r[rRfv]*f?[rRfv]*\s+/var/lib/apt/lists/\*")
_CHECK_VALID_UNTIL_RE = re.compile(
    r"Acquire::Check-Valid-Until\s*[= ]\s*['\"]?(?:false|0|no)\b",
    re.IGNORECASE,
)


def _collect_dockerfiles() -> list[Path]:
    paths: set[Path] = set()
    paths.update(_ROLES_ROOT.glob("*/files/Dockerfile"))
    paths.update(_ROLES_ROOT.glob("*/files/**/Dockerfile"))
    paths.update(_ROLES_ROOT.glob("*/templates/Dockerfile*.j2"))
    return sorted(paths)


def _iter_run_blocks(source: str):
    """Yield ``(start_lineno, joined_text)`` for every logical ``RUN`` block.

    A RUN block extends from the line beginning with ``RUN`` to the first
    line that does not end with a backslash continuation. Jinja2 control
    tags are stripped first so a RUN spanning ``{% if %}`` boundaries
    still gets scanned as one block.
    """
    cleaned = _J2_CTRL_RE.sub("", source)
    lines = cleaned.splitlines()
    i = 0
    while i < len(lines):
        if not _RUN_START_RE.match(lines[i]):
            i += 1
            continue
        start = i + 1  # 1-based line number for human-readable output
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
        upd = _APT_UPDATE_RE.search(block)
        if not upd:
            continue
        if _CHECK_VALID_UNTIL_RE.search(block):
            failures.append(
                f"{relative}:{lineno}: RUN passes "
                "`Acquire::Check-Valid-Until=false` (or =0/no). "
                "Forbidden — that flag disables apt's replay-protection "
                "on signed Release files. Refresh the lists instead."
            )
        rm = _RM_LISTS_RE.search(block)
        if not rm or rm.start() > upd.start():
            failures.append(
                f"{relative}:{lineno}: RUN calls `apt-get update` "
                "without first purging `/var/lib/apt/lists/*` in the "
                "same RUN. Stale base-image lists can fail "
                "`Valid-Until`. Prepend `rm -rf /var/lib/apt/lists/* "
                "&& ` to the RUN."
            )
    return failures


class TestDockerfileAptUpdatePurgeLists(unittest.TestCase):
    def test_apt_update_purges_lists_first_and_no_valid_until_bypass(self) -> None:
        self.assertTrue(
            _ROLES_ROOT.is_dir(),
            f"'roles' directory not found at: {_ROLES_ROOT}",
        )

        failures: list[str] = []
        for path in _collect_dockerfiles():
            failures.extend(_violations(path))

        self.assertFalse(
            failures,
            "Dockerfile `apt-get update` safety contract violated:\n\n"
            + "\n".join(f"  {f}" for f in failures),
        )


if __name__ == "__main__":
    unittest.main()
