"""Lint compose service resource limits in role configs.

Every **invokable** role's primary compose service (``services.<entity_name>``)
MUST declare the host-resource guard rails:

- ``min_storage``
- ``cpus``
- ``mem_reservation``
- ``mem_limit``
- ``pids_limit``

Scope: only roles whose directory name starts with an invokable prefix from
``roles/categories.yml`` (resolved via
``plugins.filter.invokable_paths.get_invokable_paths``) are checked. Non-
invokable categories (``sys-*``, ``dev-*``, …) are infrastructural and ship
no top-level compose service of their own.

Missing keys emit a ``::warning`` annotation each so CI annotates the source
line and **fail the test** so the regression blocks the merge.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

from plugins.filter.invokable_paths import get_invokable_paths
from utils.annotations.message import in_github_actions, warning
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.entity_name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

REQUIRED_KEYS = (
    "min_storage",
    "cpus",
    "mem_reservation",
    "mem_limit",
    "pids_limit",
)


@dataclass(frozen=True)
class MissingKeyFinding:
    role: str
    service: str
    key: str
    config_path: Path
    line: int


def _load_yaml(path: Path) -> dict:
    try:
        data = load_yaml_any(str(path), default_if_missing={})
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _find_service_line(config_path: Path, service_name: str) -> int:
    """1-based line of ``<service_name>:`` at the root of meta/services.yml.
    Falls back to 1 when unparsable so the annotation still points at the file.
    """
    pattern = re.compile(rf"^{re.escape(service_name)}\s*:\s*$")
    try:
        for i, raw in enumerate(read_text(str(config_path)).splitlines(), start=1):
            if pattern.match(raw):
                return i
    except OSError:
        # Best-effort lookup only: if the file can't be read, keep linting and
        # point the annotation at line 1 as a safe fallback.
        return 1
    return 1


def _collect_findings(root: Path) -> list[MissingKeyFinding]:
    findings: list[MissingKeyFinding] = []
    roles_dir = root / "roles"
    invokable_prefixes = tuple(get_invokable_paths(suffix="-"))
    for role_dir in sorted(roles_dir.iterdir()):
        if not role_dir.is_dir():
            continue
        if not role_dir.name.startswith(invokable_prefixes):
            continue
        config_path = role_dir / ROLE_FILE_META_SERVICES
        if not config_path.is_file():
            continue

        # meta/services.yml's root IS the services map.
        services = _load_yaml(config_path)
        if not isinstance(services, dict):
            continue

        entity_name = get_entity_name(role_dir.name)
        if not entity_name or entity_name not in services:
            continue
        primary_conf = services.get(entity_name)
        if not isinstance(primary_conf, dict):
            continue
        if primary_conf.get("shared") is True:
            continue

        service_line = _find_service_line(config_path, entity_name)
        findings.extend(
            MissingKeyFinding(
                role=role_dir.name,
                service=entity_name,
                key=key,
                config_path=config_path,
                line=service_line,
            )
            for key in REQUIRED_KEYS
            if key not in primary_conf
        )

    findings.sort(key=lambda f: (f.role, f.service, f.key))
    return findings


def _emit_warning(finding: MissingKeyFinding, root: Path) -> None:
    rel = finding.config_path.relative_to(root).as_posix()
    warning(
        f"{finding.role}: services.{finding.service}.{finding.key} is not set",
        title="Missing resource limit",
        file=rel,
        line=finding.line,
    )


def _print_summary(findings: list[MissingKeyFinding], root: Path) -> None:
    if not findings:
        return
    print()
    print(f"[WARNING] Missing compose-service resource limits ({len(findings)}):")
    for f in findings:
        rel = f.config_path.relative_to(root).as_posix()
        print(f"- {rel}:{f.line} - services.{f.service}.{f.key} ({f.role})")


class TestComposeResourceLimits(unittest.TestCase):
    def test_primary_services_declare_resource_limits(self) -> None:
        """Fail loudly when an invokable role's primary compose service is
        missing one of the required resource keys.
        """
        root = PROJECT_ROOT
        findings = _collect_findings(root)

        for finding in findings:
            _emit_warning(finding, root)

        if not in_github_actions():
            _print_summary(findings, root)

        if findings:
            lines = [
                f"{f.config_path.relative_to(root).as_posix()}:{f.line}: "
                f"services.{f.service}.{f.key} is not set ({f.role})"
                for f in findings
            ]
            self.fail(
                f"Missing required compose-service resource keys "
                f"({', '.join(REQUIRED_KEYS)}) on {len(findings)} entries:\n"
                + "\n".join(lines)
            )


if __name__ == "__main__":
    unittest.main()
