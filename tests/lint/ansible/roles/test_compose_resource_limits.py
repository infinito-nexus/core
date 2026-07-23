"""Lint compose service resource limits in role configs.

Every container service that a role runs **itself** (i.e. that is not provided
by another role via the service registry) MUST declare host-resource guard
rails, so the aggregate-resources tooling and the deploy can always resolve a
real budget instead of silently falling back to the dynamic fair-share default.

Two scopes:

- **Primary entity** (``services.<entity_name>``) of every invokable role MUST
  declare ``min_storage``, ``cpus``, ``mem_reservation``, ``mem_limit`` and
  ``pids_limit``.
- **Sidecar containers** (every other enabled, container-shaped service entry)
  MUST declare ``cpus``, ``mem_reservation``, ``mem_limit`` and ``pids_limit``
  (``min_storage`` is the role/entity's concern, not a sidecar's).

A service entry is **exempt** when another role covers it — i.e. the service
key resolves through the service registry to a *different* role (e.g.
discourse's ``postgres`` is provided by ``svc-db-postgres``, whose entity
declares the limits). Pure config toggles / cross-role integration flags that
are not container-shaped are ignored.

Scope: only roles whose directory name starts with an invokable prefix from
``roles/categories.yml`` are checked. Non-invokable categories (``dev-*``,
``sys-*``) ship no compose service of their own.

Missing keys emit a ``::warning`` annotation each so CI annotates the source
line and **fail the test** so the regression blocks the merge.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

from plugins.filter.invokable_paths import get_invokable_paths
from utils.annotations.message import in_github_actions, warning
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
    load_applications_from_roles_dir,
)
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ENTITY_REQUIRED_KEYS = (
    "min_storage",
    "cpus",
    "mem_reservation",
    "mem_limit",
    "pids_limit",
)
SIDECAR_REQUIRED_KEYS = (
    "cpus",
    "mem_reservation",
    "mem_limit",
    "pids_limit",
)
_CONTAINER_HINT_KEYS = (
    "image",
    "name",
    "version",
    "container",
    "ports",
    "backup",
    "ref",
    "repository",
    "network_mode",
    "min_storage",
    *SIDECAR_REQUIRED_KEYS,
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


def _is_enabled(service_conf: dict[str, Any]) -> bool:
    raw = service_conf.get("enabled", True)
    if isinstance(raw, bool):
        return raw
    return bool(raw)


def _looks_like_container(service_conf: dict[str, Any]) -> bool:
    return any(key in service_conf for key in _CONTAINER_HINT_KEYS)


def _covered_by_other_role(
    service_key: str,
    role: str,
    registry: dict[str, dict[str, Any]],
) -> bool:
    provider = registry.get(service_key) or {}
    provider_role = provider.get("role")
    return bool(provider_role and provider_role != role)


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
        return 1
    return 1


def _collect_findings(root: Path) -> list[MissingKeyFinding]:
    findings: list[MissingKeyFinding] = []
    roles_dir = root / "roles"
    registry = build_service_registry_from_applications(
        load_applications_from_roles_dir(roles_dir)
    )
    invokable_prefixes = tuple(get_invokable_paths(suffix="-"))
    for role_dir in sorted(roles_dir.iterdir()):
        if not role_dir.is_dir():
            continue
        if not role_dir.name.startswith(invokable_prefixes):
            continue
        config_path = role_dir / ROLE_FILE_META_SERVICES
        if not config_path.is_file():
            continue

        services = _load_yaml(config_path)
        if not isinstance(services, dict):
            continue

        entity_name = get_entity_name(role_dir.name)
        for service_key, raw_conf in services.items():
            if not isinstance(raw_conf, dict):
                continue
            is_entity = service_key == entity_name

            if not is_entity:
                if not _is_enabled(raw_conf):
                    continue
                if not _looks_like_container(raw_conf):
                    continue

            if _covered_by_other_role(service_key, role_dir.name, registry):
                continue

            required = ENTITY_REQUIRED_KEYS if is_entity else SIDECAR_REQUIRED_KEYS
            service_line = _find_service_line(config_path, service_key)
            findings.extend(
                MissingKeyFinding(
                    role=role_dir.name,
                    service=service_key,
                    key=key,
                    config_path=config_path,
                    line=service_line,
                )
                for key in required
                if key not in raw_conf
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
    def test_self_run_services_declare_resource_limits(self) -> None:
        """Fail loudly when a role's own (not externally-provided) container
        service is missing one of the required resource keys.
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
                f"Missing required compose-service resource keys on "
                f"{len(findings)} entries (entity needs {ENTITY_REQUIRED_KEYS}, "
                f"sidecar needs {SIDECAR_REQUIRED_KEYS}):\n" + "\n".join(lines)
            )


if __name__ == "__main__":
    unittest.main()
