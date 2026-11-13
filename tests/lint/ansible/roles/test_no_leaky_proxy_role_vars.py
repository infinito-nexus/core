from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.annotations.message import in_github_actions, warning
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_NOCHECK_RE = re.compile(r"#\s*nocheck:\s*leaky-proxy-var\b")
_KEY_RE = re.compile(r"^(webserver_[A-Za-z0-9_]+)\s*:")


@dataclass(frozen=True)
class LeakyVarFinding:
    role: str
    var: str
    config_path: Path
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


def _collect_findings(root: Path) -> list[LeakyVarFinding]:
    roles_dir = root / "roles"
    findings: list[LeakyVarFinding] = []
    for role_dir in sorted(roles_dir.iterdir()):
        if not role_dir.is_dir():
            continue
        vars_path = role_dir / ROLE_FILE_VARS_MAIN
        if not vars_path.is_file():
            continue
        try:
            lines = read_text(str(vars_path)).splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            match = _KEY_RE.match(line)
            if match and not _has_nocheck(lines, i):
                findings.append(
                    LeakyVarFinding(role_dir.name, match.group(1), vars_path, i + 1)
                )
    findings.sort(key=lambda f: (f.role, f.var))
    return findings


def _fix_hint(finding: LeakyVarFinding) -> str:
    return (
        f"role var '{finding.var}' in roles/{finding.role}/vars/main.yml leaks into "
        "the central front-proxy pass (it stays in play scope and is re-evaluated "
        "while other roles' vhosts render). Declare it per vhost under "
        f"server.vhosts in roles/{finding.role}/meta/server.yml instead, or add "
        "'# nocheck: leaky-proxy-var' if it must be play-wide."
    )


def _emit_warning(finding: LeakyVarFinding, root: Path) -> None:
    warning(
        _fix_hint(finding),
        title="Leaky proxy role var",
        file=finding.config_path.relative_to(root).as_posix(),
        line=finding.line,
    )


def _print_summary(findings: list[LeakyVarFinding], root: Path) -> None:
    if not findings:
        return
    print()
    print(f"[WARNING] Leaky proxy-override role vars ({len(findings)}):")
    for f in findings:
        rel = f.config_path.relative_to(root).as_posix()
        print(f"- {rel}:{f.line} - {_fix_hint(f)}")


class TestNoLeakyProxyRoleVars(unittest.TestCase):
    def test_proxy_override_vars_are_not_role_level(self) -> None:
        root = PROJECT_ROOT
        findings = _collect_findings(root)

        for finding in findings:
            _emit_warning(finding, root)

        if not in_github_actions():
            _print_summary(findings, root)

        if findings:
            lines = [
                f"{f.config_path.relative_to(root).as_posix()}:{f.line}: {_fix_hint(f)}"
                for f in findings
            ]
            self.fail(
                f"{len(findings)} leaky proxy-override role var(s) in vars/main.yml:\n"
                + "\n".join(lines)
            )


if __name__ == "__main__":
    unittest.main()
