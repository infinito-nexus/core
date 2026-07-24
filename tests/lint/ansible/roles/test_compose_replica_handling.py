"""Lint: every service entry in ``roles/*/templates/compose*.yml.j2`` MUST
declare swarm replica handling via one of three valid paths:

1. ``{% include 'roles/sys-svc-container/templates/base.yml.j2' %}`` -
   full inheritance (restart/logging/env_file + transitive deploy block).
2. ``{% include 'roles/sys-svc-container/templates/deploy.yml.j2' %}`` -
   escape hatch for services that own their restart/logging/env_file
   and therefore cannot use base.yml.j2 without duplicate-key conflicts.
   Emits only the swarm ``deploy:`` block (replicas/update_config/restart_policy/resources).
3. ``{{ lookup('compose_replicas', ...) }}`` - explicit lookup call when
   the caller assembles a custom ``deploy:`` block by hand.

This pins the SPOT for swarm replica handling: no service may silently
bypass the topology-driven default.

A "service entry" is a line at indent EXACTLY 2 ending with ``:``
(literal or Jinja-substituted) that lives under the top-level
``services:`` block. Entries under ``networks:``, ``volumes:``, anchor
blocks (``x-*:``), or other top-level sections are skipped.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

BASE_INCLUDE = "roles/sys-svc-container/templates/base.yml.j2"
DEPLOY_INCLUDE = "roles/sys-svc-container/templates/deploy.yml.j2"
LOOKUP_NAME = "compose_replicas"

SERVICE_ENTRY_RE = re.compile(r"^  (?! )\S.*:\s*$")
LOOKUP_CALL_RE = re.compile(r"lookup\(\s*['\"]" + re.escape(LOOKUP_NAME) + r"['\"]")

SVC_COMPOSE_BASE_INCLUDE = "{% include 'roles/sys-svc-compose/templates/base.yml.j2' %}"
SVC_COMPOSE_NETWORKS_INCLUDE = "{{ lookup('compose_networks') }}"

CTX_SERVICES = "services"
CTX_OTHER = "other"


@dataclass(frozen=True)
class Finding:
    role: str
    file: Path
    service: str
    line: int


SKIP_BASENAMES = {"compose.override.yml.j2", "compose-inits.yml.j2"}


def _walk_compose_templates(root: Path):
    for compose_file in sorted((root / "roles").glob("*/templates/compose*.yml.j2")):
        if compose_file.name in SKIP_BASENAMES:
            continue
        yield compose_file


def _classify_context_line(line: str) -> str | None:
    stripped_lead = line.lstrip()
    if stripped_lead is line and stripped_lead.startswith(
        ("networks:", "volumes:", "configs:", "secrets:")
    ):
        return CTX_OTHER
    if line.startswith("services:"):
        return CTX_SERVICES
    if re.match(r"^x-[^:]*:", line):
        return CTX_OTHER
    if SVC_COMPOSE_BASE_INCLUDE in line:
        return CTX_SERVICES
    if SVC_COMPOSE_NETWORKS_INCLUDE in line:
        return CTX_OTHER
    if "lookup('compose_volumes'" in line or 'lookup("compose_volumes"' in line:
        return CTX_OTHER
    return None


def _context_changes(lines: list[str]) -> list[tuple[int, str]]:
    changes: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        ctx = _classify_context_line(ln)
        if ctx is not None:
            changes.append((i, ctx))
    return changes


def _context_at(line_idx: int, changes: list[tuple[int, str]]) -> str:
    ctx = CTX_OTHER
    for idx, c in changes:
        if idx <= line_idx:
            ctx = c
        else:
            break
    return ctx


def _extract_service_blocks(text: str):
    lines = text.splitlines()
    changes = _context_changes(lines)

    candidates = [
        i
        for i, ln in enumerate(lines)
        if SERVICE_ENTRY_RE.match(ln) and _context_at(i, changes) == CTX_SERVICES
    ]

    for k, start in enumerate(candidates):
        end = candidates[k + 1] if k + 1 < len(candidates) else len(lines)
        for idx, c in changes:
            if start < idx < end and c != CTX_SERVICES:
                end = idx
                break
        name = lines[start].strip().rstrip(":").strip()
        body = "\n".join(lines[start:end])
        yield name, start + 1, body


def _is_handler_satisfied(body: str) -> bool:
    if BASE_INCLUDE in body:
        return True
    if DEPLOY_INCLUDE in body:
        return True
    return bool(LOOKUP_CALL_RE.search(body))


def _collect_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for compose_file in _walk_compose_templates(root):
        role = compose_file.parent.parent.name
        try:
            text = read_text(str(compose_file))
        except OSError:
            continue
        for name, start_line, body in _extract_service_blocks(text):
            if not _is_handler_satisfied(body):
                findings.append(
                    Finding(role=role, file=compose_file, service=name, line=start_line)
                )
    findings.sort(key=lambda f: (f.role, f.line))
    return findings


class TestComposeReplicaHandling(unittest.TestCase):
    def test_every_service_has_replica_handler(self) -> None:
        findings = _collect_findings(PROJECT_ROOT)
        if not findings:
            return
        details = "\n".join(
            f"  - {f.file.relative_to(PROJECT_ROOT).as_posix()}:{f.line} "
            f"service={f.service!r} (role={f.role})"
            for f in findings
        )
        self.fail(
            f"{len(findings)} compose service entries lack a replica handler. "
            f"Each service in roles/*/templates/compose*.yml.j2 must either "
            f"include '{BASE_INCLUDE}' OR call lookup('{LOOKUP_NAME}', ...).\n"
            f"{details}"
        )


if __name__ == "__main__":
    unittest.main()
