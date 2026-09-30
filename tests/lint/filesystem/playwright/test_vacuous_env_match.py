"""Lint guard: an env value defaulted to ``""`` MUST NOT feed a match.

``"".endsWith(x)``, ``x.includes("")`` and ``x.startsWith("")`` are true for
every string. A spec that binds ``const host = decodeDotenvQuotedValue(
process.env.CANONICAL_DOMAIN || "")`` and later asserts
``url.includes(host)`` therefore stops testing anything the moment the deploy
forgets to write that key: the assertion passes, the suite is green, and the
missing value never surfaces.

The repository already refuses the list-shaped version of this: the throwing
``decodeDotenvJsonList`` exists because reading a mis-decoded list as ``[]``
"would pass every assertion that iterates it". This rule is the scalar half.

Bind the value with ``requireDotenvValue(process.env.<KEY>, "<KEY>")`` instead,
which throws while the module loads, or keep the ``|| ""`` and guard the value
before matching on it.

Suppress on the binding line with ``// nocheck: vacuous-env-match -- <reason>``.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_BINDING_RE = re.compile(
    r"^[^\S\n]*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(.*?);[^\S\n]*$",
    re.MULTILINE,
)
_EMPTY_DEFAULT_RE = re.compile(r"\|\|\s*\"\"")
_NOCHECK_RE = re.compile(r"//\s*nocheck:\s*vacuous-env-match\b")
_MATCHERS = ("endsWith", "startsWith", "includes")


@dataclass(frozen=True)
class Violation:
    file: str
    line_no: int
    name: str
    matcher: str


def _git_ls_files() -> list[str]:
    out = subprocess.check_output(
        ["git", "-c", "safe.directory=*", "-C", str(PROJECT_ROOT), "ls-files"],
        text=True,
    )
    return [line for line in out.splitlines() if line]


def _empty_defaulted_env_names(text: str) -> set[str]:
    names: set[str] = set()
    for match in _BINDING_RE.finditer(text):
        expression = match.group(2)
        if "process.env." not in expression:
            continue
        if not _EMPTY_DEFAULT_RE.search(expression):
            continue
        if _NOCHECK_RE.search(match.group(0)):
            continue
        names.add(match.group(1))
    return names


def _scan_file(path: Path) -> list[Violation]:
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []

    names = _empty_defaulted_env_names(text)
    if not names:
        return []

    violations: list[Violation] = []
    for name in sorted(names):
        for matcher in _MATCHERS:
            pattern = re.compile(rf"\.{matcher}\(\s*{re.escape(name)}\s*\)")
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                violations.append(Violation(rel, line_no, name, matcher))
    return violations


def _scan_targets() -> list[Path]:
    return [
        PROJECT_ROOT / rel
        for rel in _git_ls_files()
        if rel.endswith(".js")
        and ("/files/playwright/" in rel or "/files/personas/" in rel)
    ]


class TestVacuousEnvMatch(unittest.TestCase):
    def test_empty_defaulted_env_values_never_feed_a_matcher(self) -> None:
        targets = _scan_targets()
        self.assertTrue(targets, "no Playwright spec files found to scan")
        violations: list[Violation] = []
        for path in targets:
            violations.extend(_scan_file(path))
        if violations:
            header = [
                f"Env values defaulted to \"\" used as a match argument "
                f"({len(violations)}):",
                "",
                "An empty string is a suffix, a prefix and a substring of every",
                "string, so these assertions pass unconditionally whenever the",
                "deploy does not write the key.",
                "",
                'Bind with `requireDotenvValue(process.env.<KEY>, "<KEY>")`, which',
                "throws at module load, or guard the value before matching on it.",
                "Suppress on the binding line with",
                "`// nocheck: vacuous-env-match -- <reason>`.",
                "",
                "Offenders:",
            ]
            body = [
                f"  {v.file}:{v.line_no}: .{v.matcher}({v.name})"
                for v in sorted(violations)
            ]
            self.fail("\n".join(header + body))


if __name__ == "__main__":
    unittest.main()
