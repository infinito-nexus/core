from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable

# Host-identity facts in a template diverge per host and corrupt the shared
# NFS-backed config view under swarm-mode replication.
_HOST_LOCAL_FACT_PATTERNS = (
    r"ansible_hostname",
    r"ansible_fqdn",
    r"ansible_nodename",
    r"ansible_default_ipv4",
    r"ansible_default_ipv6",
    r"ansible_all_ipv4_addresses",
    r"ansible_all_ipv6_addresses",
    r"ansible_machine_id",
    r"ansible_product_uuid",
    r"ansible_facts\.hostname",
    r"ansible_facts\.fqdn",
    r"ansible_facts\.nodename",
    r"ansible_facts\.default_ipv4",
    r"ansible_facts\.default_ipv6",
    r"ansible_facts\.all_ipv4_addresses",
    r"ansible_facts\.all_ipv6_addresses",
)

_BANNED_RE = re.compile("|".join(_HOST_LOCAL_FACT_PATTERNS))
_SCAN_PREFIXES = ("roles/",)
_SCAN_SUFFIXES = (".j2",)


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    match: str
    snippet: str

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        return f"{rel}:{self.line}: '{self.match}' in: {self.snippet}"


def _iter_target_files(repo_root: Path) -> Iterable[Path]:
    for abs_path in iter_project_files(extensions=_SCAN_SUFFIXES):
        rel = Path(abs_path).relative_to(repo_root).as_posix()
        if any(rel.startswith(p) for p in _SCAN_PREFIXES):
            yield Path(abs_path)


def _scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, raw in enumerate(read_text(path).splitlines(), start=1):
        findings.extend(
            Finding(
                file=path,
                line=lineno,
                match=m.group(0),
                snippet=raw.strip()[:200],
            )
            for m in _BANNED_RE.finditer(raw)
        )
    return findings


class TestNoAnsibleFactsInRoleTemplates(unittest.TestCase):
    def test_no_host_local_facts_in_role_templates(self) -> None:
        findings: list[Finding] = []
        for path in _iter_target_files(PROJECT_ROOT):
            findings.extend(_scan_file(path))
        if findings:
            header = (
                "Host-local ansible_* facts are forbidden in role templates "
                "(they diverge per host and break multi-host renders). "
                "Replace with controller-side computed values via set_fact "
                "or group_vars.\n"
            )
            body = "\n".join(f.format(PROJECT_ROOT) for f in findings)
            self.fail(header + body)


if __name__ == "__main__":
    unittest.main()
