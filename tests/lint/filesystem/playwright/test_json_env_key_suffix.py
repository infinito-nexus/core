"""Lint guard: an env key read by ``decodeDotenvJsonList`` MUST end in ``_JSON``.

``scripts/lint/playwright.sh`` cannot render the Jinja ``.env`` templates, so it
invents a stub value from the variable-name suffix alone. Only
``*_JSON|*JSON|*SLUGS|*OVERRIDE`` receive ``[]``; every other key receives the
literal string ``stub``.

``decodeDotenvJsonList`` throws on a value that cannot be a list, and the spec
modules decode at module scope. A list-valued key without the suffix therefore
makes ``playwright test --list`` die before it collects anything, and the lint
reports ``No tests found`` on a spec whose tests are all present -- the cause is
one env key away from the message. ``SEAWEEDFS_CONSUMER_BUCKETS`` failed exactly
this way.

Suppress on the ``process.env.<KEY>`` line with
``// nocheck: json-env-key-suffix -- <reason>``.
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

_DECODE_RE = re.compile(
    r"decodeDotenvJsonList\s*\(\s*process\.env\.([A-Za-z_][A-Za-z0-9_]*)"
)
_NOCHECK_RE = re.compile(r"(?://|#)\s*nocheck:\s*json-env-key-suffix\b")
_REQUIRED_SUFFIX = "_JSON"


@dataclass(frozen=True)
class Violation:
    file: str
    line_no: int
    key: str


def _git_ls_files() -> list[str]:
    out = subprocess.check_output(
        ["git", "-c", "safe.directory=*", "-C", str(PROJECT_ROOT), "ls-files"],
        text=True,
    )
    return [line for line in out.splitlines() if line]


def _scan_file(path: Path) -> list[Violation]:
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []

    lines = text.splitlines()
    violations: list[Violation] = []
    for m in _DECODE_RE.finditer(text):
        key = m.group(1)
        if key.endswith(_REQUIRED_SUFFIX):
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        window = "\n".join(lines[line_no - 1 : line_no + 1])
        if _NOCHECK_RE.search(window):
            continue
        violations.append(Violation(rel, line_no, key))
    return violations


def _scan_targets() -> list[Path]:
    return [
        PROJECT_ROOT / rel
        for rel in _git_ls_files()
        if rel.endswith(".js") and "/files/playwright/" in rel
    ]


class TestJsonEnvKeySuffix(unittest.TestCase):
    def test_json_list_env_keys_carry_the_json_suffix(self) -> None:
        targets = _scan_targets()
        self.assertTrue(targets, "no Playwright spec files found to scan")
        violations: list[Violation] = []
        for path in targets:
            violations.extend(_scan_file(path))
        if violations:
            header = [
                (
                    f"JSON-list env keys without the `{_REQUIRED_SUFFIX}` "
                    f"suffix ({len(violations)}):"
                ),
                "",
                "`scripts/lint/playwright.sh` stubs env values by name suffix and",
                "gives `[]` only to `*_JSON|*JSON|*SLUGS|*OVERRIDE`. Any other key",
                "gets the literal `stub`, `decodeDotenvJsonList` throws at module",
                "scope, and `playwright test --list` reports `No tests found`.",
                "",
                "Rename the key on BOTH sides (the spec and the role's",
                "`templates/playwright.env.j2`), or suppress on the",
                "`process.env.<KEY>` line with",
                "`// nocheck: json-env-key-suffix -- <reason>`.",
                "",
                "Offenders:",
            ]
            body = [f"  {v.file}:{v.line_no}: {v.key}" for v in sorted(violations)]
            self.fail("\n".join(header + body))


if __name__ == "__main__":
    unittest.main()
