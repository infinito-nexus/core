"""Warn about templated Dockerfiles that should become plain files.

Roles that still ship ``templates/Dockerfile.j2`` are reported as warnings so
that maintainers can migrate them to ``files/Dockerfile`` over time without
blocking CI.

Two distinct warnings are emitted depending on the file content:

- **No Jinja2 logic** (only ``{{ variable }}`` substitutions or plain text):
  The file can be migrated to a plain ``files/Dockerfile`` by replacing
  variables with Docker ``ARG`` declarations and passing them via the compose
  build ``args`` block.
- **Jinja2 control-flow logic** (``{% if %}``, ``{% for %}``, etc.):
  The conditional logic prevents a direct one-to-one migration.  The warning
  remains because maintainers should still consider whether the logic can be
  eliminated or split into separate Dockerfiles.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.annotations.message import warning
from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_REPO_ROOT = PROJECT_ROOT
_ROLES_ROOT = _REPO_ROOT / "roles"

# Matches any Jinja2 control-flow or structural tag: {% ... %}
_J2_LOGIC_RE = re.compile(r"\{%-?\s*\w")


def _has_j2_logic(dockerfile_j2: Path) -> bool:
    """Return True if the file contains at least one Jinja2 block tag."""
    return bool(_J2_LOGIC_RE.search(read_text(str(dockerfile_j2))))


def _collect_templated_dockerfiles() -> list[Path]:
    templated: list[Path] = []
    for dockerfile_j2 in sorted(_ROLES_ROOT.glob("*/templates/Dockerfile.j2")):
        # nocheck: project-root-import  walking from a discovered glob match (<role>/templates/...) up to its role dir, not the repo root
        plain_dockerfile = dockerfile_j2.parents[1] / "files" / "Dockerfile"
        if plain_dockerfile.is_file():
            continue
        templated.append(dockerfile_j2)
    return templated


def _warning_message(relative_path: str, has_logic: bool) -> str:
    if has_logic:
        return (
            f"{relative_path} uses Dockerfile.j2 with Jinja2 control-flow logic. "
            "Consider whether the conditional logic can be eliminated or split into "
            "separate Dockerfiles to allow migration to a plain files/Dockerfile."
        )
    return (
        f"{relative_path} uses Dockerfile.j2 instead of files/Dockerfile. "
        "Prefer a plain Dockerfile because Dockerfiles are easier to test and "
        "maintain and provide better separation of concerns. "
        "Variables can be passed as Docker ARG declarations via the compose build args block."
    )


def _emit_warning(dockerfile_j2: Path) -> None:
    relative_path = dockerfile_j2.relative_to(_REPO_ROOT).as_posix()
    has_logic = _has_j2_logic(dockerfile_j2)
    message = _warning_message(relative_path, has_logic)
    warning(message, title="Templated Dockerfile", file=relative_path)


class TestDockerfileTemplates(unittest.TestCase):
    """Warn when roles still use templates/Dockerfile.j2."""

    def test_dockerfile_j2_warns_only(self) -> None:
        self.assertTrue(
            _ROLES_ROOT.is_dir(), f"'roles' directory not found at: {_ROLES_ROOT}"
        )

        templated = _collect_templated_dockerfiles()

        failures: list[Path] = []
        for dockerfile_j2 in templated:
            _emit_warning(dockerfile_j2)
            if not _has_j2_logic(dockerfile_j2):
                failures.append(dockerfile_j2)

        self.assertFalse(
            failures,
            "The following Dockerfile.j2 files contain no Jinja2 control-flow logic "
            "and MUST be migrated to plain files/Dockerfile:\n"
            + "\n".join(f"  {p.relative_to(_REPO_ROOT).as_posix()}" for p in failures),
        )


if __name__ == "__main__":
    unittest.main()
