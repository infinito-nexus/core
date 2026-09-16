"""Lint: a test role must never carry ``no_log``.

``roles/test-*`` run only in CI, against a throwaway cluster whose credentials
are generated per deploy and thrown away with it. ``no_log`` there protects
nothing and costs the one thing a red test job is for: the output that says
what failed. A masked task reports ``the output has been hidden`` and the
operator has to re-run the whole matrix round to learn what a single assertion
saw.

The rule is absolute, so it carries no ``nocheck`` escape hatch. When a test
task's output looks too sensitive to print, extract the field the assertion
needs instead of blinding the task.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.annotations.message import in_github_actions, warning
from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_NO_LOG_RE = re.compile(r"^\s*no_log\s*:")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    text: str


def _collect_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for yaml_file in sorted(root.glob("roles/test-*/**/*.yml")):
        try:
            lines = read_text(str(yaml_file)).splitlines()
        except OSError:
            continue
        rel = yaml_file.relative_to(root).as_posix()
        findings.extend(
            Finding(rel, number, line.strip())
            for number, line in enumerate(lines, start=1)
            if _NO_LOG_RE.match(line)
        )
    return findings


def _fix_hint(rel: str) -> str:
    return (
        f"{rel} uses no_log in a test role. Test roles run in CI against "
        "throwaway credentials, so no_log hides the failure output without "
        "protecting anything. Drop it; if a value is genuinely too large or "
        "noisy to print, extract the field the assertion reads."
    )


class TestNoNoLogInTestRoles(unittest.TestCase):
    def test_test_roles_carry_no_no_log(self) -> None:
        findings = _collect_findings(PROJECT_ROOT)

        for finding in findings:
            warning(
                _fix_hint(finding.path),
                title="no_log in a test role",
                file=finding.path,
                line=finding.line,
            )

        if findings and not in_github_actions():
            print()
            print(f"[WARNING] no_log in test roles ({len(findings)}):")
            for finding in findings:
                print(f"- {finding.path}:{finding.line}: {finding.text}")

        if findings:
            self.fail(
                f"{len(findings)} no_log entr(ies) in roles/test-*:\n"
                + "\n".join(f"{f.path}:{f.line}: {_fix_hint(f.path)}" for f in findings)
            )

    def test_the_scan_reaches_the_test_roles(self) -> None:
        """A glob that matches nothing would pass vacuously forever."""
        scanned = sorted(PROJECT_ROOT.glob("roles/test-*/**/*.yml"))
        self.assertTrue(
            scanned,
            "no YAML found under roles/test-*; the glob no longer reaches the "
            "test roles, so the rule above cannot fire",
        )


if __name__ == "__main__":
    unittest.main()
