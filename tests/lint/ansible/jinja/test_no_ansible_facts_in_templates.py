"""Lint: a host-local fact must not reach a role template.

Such a fact describes whichever host the render happened on, which is not the
host the rendered file will be used by once a stack spans several. Where the
two genuinely coincide - a manager-pinned role writing a file only that node
consumes - the exception is declared rather than left to look like an oversight.

The rule reads both ``ansible_facts.default_ipv4`` and
``ansible_facts['default_ipv4']``, and it reads a role's ``vars`` and
``defaults`` as well as its templates: a fact assigned to a variable there
reaches the template just the same, and for a while the only real violation in
the tree sat in exactly that blind spot.

Only facts that ADDRESS a host are banned - its names, its ids, and any
interface's ``ipv4``/``ipv6``. Facts that describe its PLATFORM are not:
``os_family``, ``architecture`` and ``processor_vcpus`` pick behaviour for the
node the rendered file is consumed on, which is the node it was rendered for.
Banning those too would need a suppression on five correct lines out of seven.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: host-local-fact`` on, or directly above, the line.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable

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
)

_HOST_LOCAL_FACT_KEYS = (
    "hostname",
    "fqdn",
    "nodename",
    "default_ipv4",
    "default_ipv6",
    "all_ipv4_addresses",
    "all_ipv6_addresses",
)

_RULE = "host-local-fact"

_INTERFACE_ADDRESS_PATTERNS = (
    r"ansible_facts\[['\"][^'\"]+['\"]\]\[['\"]ipv[46]['\"]\]",
    r"ansible_facts\.\w+\.ipv[46]\b",
    r"ansible_\w+\[['\"]ipv[46]['\"]\]",
    r"ansible_\w+\.ipv[46]\b",
)

_BANNED_RE = re.compile(
    "|".join(
        (
            *_HOST_LOCAL_FACT_PATTERNS,
            *_INTERFACE_ADDRESS_PATTERNS,
            *(rf"ansible_facts\.{key}" for key in _HOST_LOCAL_FACT_KEYS),
            *(rf"ansible_facts\[['\"]{key}['\"]\]" for key in _HOST_LOCAL_FACT_KEYS),
        )
    )
)
_SCAN_PREFIXES = ("roles/",)
_SCAN_SUFFIXES = (".j2", ".yml")
_SCANNED_YML = (ROLE_FILE_VARS_MAIN, ROLE_FILE_DEFAULTS_MAIN)


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
        if not any(rel.startswith(p) for p in _SCAN_PREFIXES):
            continue
        if rel.endswith(".j2") or rel.endswith(_SCANNED_YML):
            yield Path(abs_path)


def _scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    lines = read_text(path).splitlines()
    for lineno, raw in enumerate(lines, start=1):
        if is_suppressed_at(lines, lineno, _RULE):
            continue
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
