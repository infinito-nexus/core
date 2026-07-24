"""Enforce parameterized FROM lines in role Dockerfiles.

Every ``FROM`` instruction in ``roles/*/files/**/Dockerfile`` and
``roles/*/templates/**/Dockerfile.j2`` MUST reference at least one
variable (Docker ``${...}`` ARG or Jinja2 ``{{ ... }}`` placeholder).
Hardcoded image references like ``FROM python:3.13-slim`` are forbidden
because the base image and tag MUST be surfaced via the role's
``meta/services.yml`` -> ``vars/main.yml`` -> build-arg chain so
operators can pin or override the base without editing the Dockerfile.

The well-known sentinel ``FROM scratch`` is allowed since it has no
upstream image to parameterize, and so is a ``FROM`` that references a
stage declared earlier in the same file (``FROM <base> AS build`` ...
``FROM build``): stage references are file-internal, not image pins.
To opt a single FROM out of the rule (e.g. a multi-stage helper that
pins to a specific scratch-built tool image), append the comment marker
``# nocheck: from-parameterized`` on the same line.
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

_FROM_RE = re.compile(r"^\s*FROM\s+(.+?)\s*$", re.IGNORECASE)
_ARG_VAR_RE = re.compile(r"\$\{[A-Z_][A-Z0-9_]*\}|\{\{\s*[A-Za-z_][\w.]*\s*\}\}")
_NOCHECK_RE = re.compile(r"#\s*nocheck:\s*from-parameterized\b")


def _collect_role_dockerfiles() -> list[Path]:
    candidates: list[Path] = []
    candidates.extend(sorted(_ROLES_ROOT.glob("*/files/**/Dockerfile")))
    candidates.extend(sorted(_ROLES_ROOT.glob("*/templates/**/Dockerfile.j2")))
    return candidates


def _from_violations(dockerfile: Path) -> list[tuple[int, str]]:
    violations: list[tuple[int, str]] = []
    stage_names: set[str] = set()
    for lineno, raw in enumerate(read_text(str(dockerfile)).splitlines(), start=1):
        line = raw.split("#", 1)[0]
        match = _FROM_RE.match(line)
        if not match:
            continue
        parts = re.split(r"\s+AS\s+", match.group(1), flags=re.IGNORECASE)
        image_ref = parts[0].strip()
        if len(parts) > 1:
            stage_names.add(parts[1].strip().lower())
        if image_ref.lower() == "scratch":
            continue
        if image_ref.lower() in stage_names:
            continue
        if _NOCHECK_RE.search(raw):
            continue
        if _ARG_VAR_RE.search(image_ref):
            continue
        violations.append((lineno, raw.strip()))
    return violations


class TestDockerfileFromParameterized(unittest.TestCase):
    """FROM in role Dockerfiles MUST reference an ARG or Jinja variable."""

    def test_role_dockerfile_from_is_parameterized(self) -> None:
        self.assertTrue(
            _ROLES_ROOT.is_dir(),
            f"'roles' directory not found at: {_ROLES_ROOT}",
        )

        findings: list[str] = []
        for dockerfile in _collect_role_dockerfiles():
            for lineno, line in _from_violations(dockerfile):
                rel = dockerfile.relative_to(_REPO_ROOT).as_posix()
                findings.append(f"  {rel}:{lineno}: {line}")

        self.assertFalse(
            findings,
            "Role Dockerfile FROM instructions must reference an ARG or Jinja "
            "variable so the base image is surfaced via "
            "meta/services.yml -> vars/main.yml -> build-arg. Hardcoded "
            "images are forbidden. Offenders:\n" + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
