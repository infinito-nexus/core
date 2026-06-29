"""Ansible internals MUST NOT pull `default.env` keys via `lookup('env', ...)`.

Inject deployment-specific values via the inventory vars-file (dev/CI:
`inventories/development/default.yml`). Suppress per line with a
same-line `# nocheck: <reason>` marker if genuinely required.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_DEFAULT_ENV_KEY_RE = re.compile(r"^\s*(?P<key>INFINITO_[A-Z0-9_]+)\s*=")
_LOOKUP_ENV_RE = re.compile(
    r"""lookup\(\s*['"]env['"]\s*,\s*['"](?P<key>INFINITO_[A-Z0-9_]+)['"]"""
)
_NOCHECK_RE = re.compile(r"#\s*nocheck\b")

# Scan trees that participate in Ansible runtime. `inventories/development/`
# is the agreed home for env-driven dev/CI overrides and is excluded; other
# inventories carry literal values and stay in scope.
_SCAN_PREFIXES = ("group_vars/", "tasks/", "roles/")
_SCAN_FILES = ("playbook.yml",)
_SCAN_EXTS = (".yml", ".yaml", ".j2")


@dataclass(frozen=True)
class _Violation:
    file: str
    line_no: int
    key: str
    line: str


def _default_env_keys(path: Path) -> set[str]:
    return {
        match.group("key")
        for line in read_text(str(path)).splitlines()
        if (match := _DEFAULT_ENV_KEY_RE.match(line)) is not None
    }


def _iter_target_files() -> list[Path]:
    out: list[Path] = []
    for path_str in iter_project_files(extensions=_SCAN_EXTS):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if rel in _SCAN_FILES or any(rel.startswith(p) for p in _SCAN_PREFIXES):
            out.append(Path(path_str))
    return sorted(out)


def _scan_file(path: Path, declared_keys: set[str]) -> list[_Violation]:
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    out: list[_Violation] = []
    for index, line in enumerate(read_text(str(path)).splitlines(), start=1):
        if _NOCHECK_RE.search(line):
            continue
        for match in _LOOKUP_ENV_RE.finditer(line):
            key = match.group("key")
            if key in declared_keys:
                out.append(_Violation(rel, index, key, line.strip()))
    return out


class TestNoAnsibleEnvLookupsForDefaultEnvKeys(unittest.TestCase):
    def test_ansible_internals_do_not_lookup_default_env_keys(self) -> None:
        default_env_path = PROJECT_ROOT / "default.env"
        self.assertTrue(default_env_path.is_file(), "default.env not found")

        declared = _default_env_keys(default_env_path)
        self.assertTrue(declared, "default.env has no INFINITO_* entries")

        targets = _iter_target_files()
        self.assertTrue(targets, "no Ansible-internal files found to scan")

        violations: list[_Violation] = []
        for path in targets:
            violations.extend(_scan_file(path, declared))

        if not violations:
            return

        lines = [
            f"Ansible internals reference {len(violations)} default.env "
            f"key(s) via lookup('env', ...):",
            "",
            "default.env is the dev/CI env contract; pulling those keys directly inside group_vars / tasks / roles / playbook.yml couples deployment-agnostic Ansible code to a deployment-specific source. Inject the value via the inventory vars-file instead. For dev/CI this is `inventories/development/default.yml`:",
            "",
            "    # inventories/development/default.yml",
            "    networks:",
            "      internet:",
            "        ip4: \"{{ lookup('env', 'INFINITO_IP4') | default('127.0.0.1', true) }}\"",
            "        ip6: \"{{ lookup('env', 'INFINITO_IP6') | default('::1', true) }}\"",
            "        dns: \"{{ lookup('env', 'INFINITO_DNS_IP') | default('') }}\"",
            "",
            "Production / bundle inventories carry literal values without the env lookup. Suppress per line with a same-line `# nocheck: <reason>` marker only when the reference is genuinely required.",
            "",
            "Offenders:",
        ]
        lines.extend(
            f"  {v.file}:{v.line_no}: {v.key}  -- {v.line}" for v in violations
        )
        self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
