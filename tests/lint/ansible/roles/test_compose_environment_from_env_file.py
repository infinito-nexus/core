"""Lint guard: a compose template MUST NOT declare ``environment:`` inline.

A container's environment belongs in ``roles/<role>/templates/env.j2``. The
shared container base wires it in on its own: ``sys-svc-container``'s
base.yml.j2 emits ``env_file`` whenever the role ``has_env``, so a role that
ships ``env.j2`` needs no ``environment:`` key at all. 89 roles already carry
one.

An inline mapping in the compose template splits the same contract over two
files, and the half in the compose template is the half nobody greps when
they go looking for what a container is configured with. A secret written
there also lands in ``docker inspect`` output, where the env file does not.

Allowed:

* No ``environment:`` at all, with the values in ``templates/env.j2``.
* ``environment:`` whose value is on the same line, which is a variable or
  an empty mapping rather than a declaration.

Forbidden:

* A block mapping of keys written inline under ``environment:``.

Suppress with a ``# nocheck: compose-environment-from-env-file`` marker on
the ``environment:`` line, on the contiguous comment lines above it, or in
the template's leading comment block. Use it where a key genuinely cannot
live in the env file, for example one a Jinja loop varies per service
instance.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

RULE = "compose-environment-from-env-file"
COMPOSE_GLOB = f"roles/*/{ROLE_FILE_TEMPL_COMPOSE}"
EXTRA_COMPOSE_GLOB = "roles/*/templates/*compose*.yml.j2"
_ENVIRONMENT_RE = re.compile(r"^(?P<indent>\s*)environment:(?P<rest>.*)$")
_NOCHECK_RE = re.compile(rf"#\s*nocheck:\s*{re.escape(RULE)}\b")
_COMMENT_RE = re.compile(r"#.*$")


@dataclass(frozen=True)
class Violation:
    file: str
    line_no: int


def _header(lines: list[str]) -> list[str]:
    """Return the file's leading comment block.

    Args:
        lines: the template's lines.
    """
    header = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            header.append(line)
            continue
        if stripped.startswith(("#", "{#")):
            header.append(line)
            continue
        break
    return header


def _suppressed(lines: list[str], index: int) -> bool:
    """Whether a nocheck naming this rule covers the line at *index*."""
    if _NOCHECK_RE.search(lines[index]):
        return True
    if any(_NOCHECK_RE.search(line) for line in _header(lines)):
        return True
    above = index - 1
    while above >= 0 and lines[above].lstrip().startswith("#"):
        if _NOCHECK_RE.search(lines[above]):
            return True
        above -= 1
    return False


def _opens_block(lines: list[str], index: int, indent: str) -> bool:
    """Whether the ``environment:`` at *index* opens a block mapping."""
    for line in lines[index + 1 :]:
        if not line.strip() or line.lstrip().startswith(("#", "{#", "{%")):
            continue
        return len(line) - len(line.lstrip()) > len(indent)
    return False


def _violations(path) -> list[Violation]:
    rel = str(path.relative_to(PROJECT_ROOT))
    lines = read_text(str(path)).splitlines()
    found = []
    for index, line in enumerate(lines):
        match = _ENVIRONMENT_RE.match(line)
        if not match:
            continue
        if _COMMENT_RE.sub("", match.group("rest")).strip():
            continue
        if not _opens_block(lines, index, match.group("indent")):
            continue
        if _suppressed(lines, index):
            continue
        found.append(Violation(rel, index + 1))
    return found


class TestComposeEnvironmentFromEnvFile(unittest.TestCase):
    def test_compose_templates_keep_their_environment_in_env_j2(self) -> None:
        paths = set(PROJECT_ROOT.glob(COMPOSE_GLOB)) | set(
            PROJECT_ROOT.glob(EXTRA_COMPOSE_GLOB)
        )
        offenders: list[Violation] = []
        for path in sorted(paths):
            offenders.extend(_violations(path))

        report = "\n".join(f"  - {v.file}:{v.line_no}" for v in offenders)
        self.assertFalse(
            offenders,
            f"{len(offenders)} compose template(s) declare environment: inline "
            "instead of keeping it in templates/env.j2:\n"
            f"{report}\n\n"
            "Move the keys to roles/<role>/templates/env.j2. The container base "
            "emits env_file for a role that has one, so the compose template "
            "needs no environment: key.\n"
            f"Suppress with `# nocheck: {RULE}` where a key cannot live there.",
        )


class TestSuppression(unittest.TestCase):
    MARKER = f"# nocheck: {RULE}  reason"

    def test_a_marker_on_the_environment_line_suppresses_it(self) -> None:
        lines = ["services:", "  a:", f"    environment: {self.MARKER}", "      K: v"]

        self.assertTrue(_suppressed(lines, 2))

    def test_a_marker_in_the_leading_comment_block_suppresses_the_file(self) -> None:
        lines = [f"{{# {self.MARKER} #}}", "services:", "  a:", "    environment:"]

        self.assertTrue(_suppressed(lines, 3))

    def test_a_marker_below_the_leading_block_covers_only_its_own_line(self) -> None:
        lines = [
            "services:",
            "  a:",
            f"    environment: {self.MARKER}",
            "      K: v",
            "  b:",
            "    environment:",
            "      K: v",
        ]

        self.assertFalse(
            _suppressed(lines, 5),
            "a marker written for one service must not silence a later block",
        )


if __name__ == "__main__":
    unittest.main()
