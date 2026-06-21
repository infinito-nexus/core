"""Lint: an addon's ``enabled`` flag must never derive from ``group_names``.

Addons (``roles/*/meta/addons/*.yml``) are gated by their ``enabled``
expression. That expression MUST defer to the owning role's service flag
(``lookup('config', '<role>', 'services.<x>.enabled')``), a literal
``true``/``false``, or one/more ``api`` lookups — never a raw
``'<role>' in group_names`` test. ``group_names`` belongs in the service
definition (``meta/services.yml``, the SPOT); the addon reads the resolved
service flag so a single source decides whether a partner is present.

Add ``# nocheck: addon-enabled-group-names`` on (or directly above) the
``enabled:`` line for a genuine exception (e.g. an anti-dependency on a
partner that has no service flag).
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.annotations.message import in_github_actions, warning
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_NOCHECK_RE = re.compile(r"#\s*nocheck:\s*addon-enabled-group-names\b")
_ENABLED_RE = re.compile(r"^\s*enabled\s*:")


@dataclass(frozen=True)
class Finding:
    addon: str
    line: int


def _has_nocheck(lines: list[str], idx: int) -> bool:
    if _NOCHECK_RE.search(lines[idx]):
        return True
    above = idx - 1
    while above >= 0 and lines[above].lstrip().startswith("#"):
        if _NOCHECK_RE.search(lines[above]):
            return True
        above -= 1
    return False


def _enabled_line(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        if _ENABLED_RE.match(line):
            return i
    return 0


def _collect_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for addon in sorted(root.glob("roles/*/meta/addons/*.yml")):
        try:
            data = load_yaml_any(str(addon), default_if_missing=None)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        enabled = data.get("enabled")
        if enabled is None or "group_names" not in str(enabled):
            continue
        try:
            lines = read_text(str(addon)).splitlines()
        except OSError:
            continue
        idx = _enabled_line(lines)
        if _has_nocheck(lines, idx):
            continue
        findings.append(Finding(addon.relative_to(root).as_posix(), idx + 1))
    findings.sort(key=lambda f: f.addon)
    return findings


def _fix_hint(rel: str) -> str:
    return (
        f"addon {rel} gates 'enabled' on group_names. Defer to the owning "
        "role's service flag (lookup config services.<x>.enabled), a literal "
        "true/false, or api lookups; move the group_names test into the role's "
        "meta/services.yml. Add '# nocheck: addon-enabled-group-names' for a "
        "genuine exception."
    )


class TestAddonEnabledNoGroupNames(unittest.TestCase):
    def test_addon_enabled_does_not_use_group_names(self) -> None:
        findings = _collect_findings(PROJECT_ROOT)

        for finding in findings:
            warning(
                _fix_hint(finding.addon),
                title="Addon enabled uses group_names",
                file=finding.addon,
                line=finding.line,
            )

        if findings and not in_github_actions():
            print()
            print(
                f"[WARNING] addons gating 'enabled' on group_names ({len(findings)}):"
            )
            for finding in findings:
                print(f"- {finding.addon}:{finding.line}")

        if findings:
            self.fail(
                f"{len(findings)} addon(s) gate 'enabled' on group_names:\n"
                + "\n".join(
                    f"{f.addon}:{f.line}: {_fix_hint(f.addon)}" for f in findings
                )
            )


if __name__ == "__main__":
    unittest.main()
