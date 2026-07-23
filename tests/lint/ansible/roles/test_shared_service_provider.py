"""Lint: every referenced shared service is actually provided by a role.

A role declares a dependency on a shared service by adding an entry under
``services`` that is enabled + shared but carries no resources of its own (e.g.
``web-app-nextcloud`` declares ``services.openproject: {enabled: ..., shared:
...}``). That reference only resolves if **some** role registers the service as
a provider — i.e. declares it with ``shared: true`` on its own entity, which is
what ``build_service_registry_from_applications`` indexes.

This lint walks every ``meta/services.yml``, collects the shared references that
have **no registered provider**, and — when the service name matches the entity
of an existing role (e.g. service ``openproject`` ↔ role ``web-app-openproject``)
or, failing that, any role that declares the service (its provider) — fails,
because that role exists but does not expose the service.

Fix on failure: in the providing role's ``meta/services.yml`` set
``services.<entity>.shared: true`` (and ``enabled: true``) so the service
registry picks it up. If the name genuinely does NOT describe a shared service
(e.g. a bridged partner app that is only co-deployed, not consumed as a shared
backend), add ``# nocheck: shared-provider`` on that role's ``services.<entity>:``
line instead. Only add the nocheck when it really is not a shared service.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

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

_RESOURCE_KEYS = ("mem_reservation", "mem_limit", "pids_limit", "cpus")
_CONTAINER_KEYS = ("image", "name", "version", "container")
_NOCHECK_RE = re.compile(r"#\s*nocheck:\s*shared-provider\b")


@dataclass(frozen=True)
class ProviderFinding:
    role: str
    service: str
    referenced_by: tuple[str, ...]
    config_path: Path
    line: int


def _load_yaml(path: Path) -> dict:
    try:
        data = load_yaml_any(str(path), default_if_missing={})
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() not in ("", "false", "0", "no", "off")


def _has_resource_keys(conf: dict[str, Any]) -> bool:
    return any(key in conf for key in _RESOURCE_KEYS)


def _looks_like_container(conf: dict[str, Any]) -> bool:
    return any(key in conf for key in _RESOURCE_KEYS + _CONTAINER_KEYS)


def _is_active(conf: dict[str, Any]) -> bool:
    if "enabled" not in conf:
        return _looks_like_container(conf)
    return _is_truthy(conf.get("enabled"))


def _find_service_line(config_path: Path, service_name: str) -> int:
    pattern = re.compile(rf"^{re.escape(service_name)}\s*:\s*$")
    try:
        for i, raw in enumerate(read_text(str(config_path)).splitlines(), start=1):
            if pattern.match(raw):
                return i
    except OSError:
        return 1
    return 1


def _has_nocheck(config_path: Path, service_name: str) -> bool:
    """True when ``# nocheck: shared-provider`` is set on the role's
    ``<service_name>:`` block: on the key line, its contiguous comment block
    above, or any of its indented child lines."""
    try:
        lines = read_text(str(config_path)).splitlines()
    except OSError:
        return False
    key_re = re.compile(rf"^{re.escape(service_name)}\s*:")
    for i, line in enumerate(lines):
        if not key_re.match(line):
            continue
        if _NOCHECK_RE.search(line):
            return True
        above = i - 1
        while above >= 0 and lines[above].lstrip().startswith("#"):
            if _NOCHECK_RE.search(lines[above]):
                return True
            above -= 1
        below = i + 1
        while below < len(lines) and (
            not lines[below].strip() or lines[below].startswith((" ", "\t", "#"))
        ):
            if _NOCHECK_RE.search(lines[below]):
                return True
            below += 1
        return False
    return False


def _collect_findings(root: Path) -> list[ProviderFinding]:
    roles_dir = root / "roles"
    applications = load_applications_from_roles_dir(roles_dir)
    registry = build_service_registry_from_applications(applications)

    entity_to_role: dict[str, str] = {}
    for role in applications:
        entity = get_entity_name(role)
        if entity:
            entity_to_role.setdefault(entity, role)

    responsible_role: dict[str, str] = dict(entity_to_role)

    referenced_by: dict[str, list[str]] = {}
    for role_dir in sorted(roles_dir.iterdir()):
        if not role_dir.is_dir():
            continue
        config_path = role_dir / ROLE_FILE_META_SERVICES
        if not config_path.is_file():
            continue
        services = _load_yaml(config_path)
        if not isinstance(services, dict):
            continue
        entity_name = get_entity_name(role_dir.name)
        for service_key, raw_conf in services.items():
            responsible_role.setdefault(service_key, role_dir.name)
            if service_key == entity_name or not isinstance(raw_conf, dict):
                continue
            if not _is_active(raw_conf) or _has_resource_keys(raw_conf):
                continue
            if not _is_truthy(raw_conf.get("shared")):
                continue
            provider = registry.get(service_key) or {}
            if provider.get("role"):
                continue
            referenced_by.setdefault(service_key, []).append(role_dir.name)

    findings: list[ProviderFinding] = []
    for service_key, refs in sorted(referenced_by.items()):
        provider_role = responsible_role.get(service_key)
        if not provider_role:
            continue
        provider_config = roles_dir / provider_role / ROLE_FILE_META_SERVICES
        if _has_nocheck(provider_config, service_key):
            continue
        findings.append(
            ProviderFinding(
                role=provider_role,
                service=service_key,
                referenced_by=tuple(sorted(set(refs))),
                config_path=provider_config,
                line=_find_service_line(provider_config, service_key),
            )
        )

    findings.sort(key=lambda f: (f.role, f.service))
    return findings


def _fix_hint(finding: ProviderFinding) -> str:
    return (
        f"shared service '{finding.service}' is referenced by "
        f"{', '.join(finding.referenced_by)} but role '{finding.role}' does not "
        f"register it. Set services.{finding.service}.shared: true (and enabled: "
        f"true) in roles/{finding.role}/meta/services.yml, or add "
        f"'# nocheck: shared-provider' on its services.{finding.service}: line if "
        f"it is not a shared service."
    )


def _emit_warning(finding: ProviderFinding, root: Path) -> None:
    rel = finding.config_path.relative_to(root).as_posix()
    warning(
        _fix_hint(finding),
        title="Unprovided shared service",
        file=rel,
        line=finding.line,
    )


def _print_summary(findings: list[ProviderFinding], root: Path) -> None:
    if not findings:
        return
    print()
    print(f"[WARNING] Referenced shared services without a provider ({len(findings)}):")
    for f in findings:
        rel = f.config_path.relative_to(root).as_posix()
        print(f"- {rel}:{f.line} - {_fix_hint(f)}")


class TestSharedServiceProvider(unittest.TestCase):
    def test_referenced_shared_services_have_a_provider(self) -> None:
        """Fail when a shared service is referenced but the role whose entity
        matches its name does not register it as a provider."""
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
                f"{len(findings)} referenced shared service(s) have no provider:\n"
                + "\n".join(lines)
            )


if __name__ == "__main__":
    unittest.main()
