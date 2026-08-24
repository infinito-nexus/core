"""Lint: enabled + shared services declare a ``bond`` importance factor.

``bond`` is a number in the closed range ``0..1`` expressing how strongly a
service is tied to the overall integration:

- ``bond: 1`` — fully bonded, always required.
- ``bond: 0`` — unbonded, never required (safe to omit).
- floats in between rank partial / optional coupling strength.

This is groundwork for tooling that later scores how important each service is
for the whole integration and decides which services may be dropped. (Named
``bond`` rather than ``bound`` to avoid confusion with the resource *bounds* /
limits enforced by ``test_compose_resource_limits``.)

Enforced rule: any service entry that is **both enabled and shared** MUST
declare a valid ``bond``. ``enabled`` / ``shared`` count as set when present
and truthy — either literal ``true`` or a non-false template expression (e.g.
``"{{ 'web-app-keycloak' in group_names }}"``).

Missing / invalid values emit a ``::warning`` annotation each so CI annotates
the source line and **fail the test** so the regression blocks the merge.
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
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class BondFinding:
    role: str
    service: str
    problem: str
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


def _valid_bond(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return 0.0 <= float(value) <= 1.0
    return False


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


def _collect_findings(root: Path) -> list[BondFinding]:
    findings: list[BondFinding] = []
    roles_dir = root / "roles"
    for role_dir in sorted(roles_dir.iterdir()):
        if not role_dir.is_dir():
            continue
        config_path = role_dir / ROLE_FILE_META_SERVICES
        if not config_path.is_file():
            continue

        services = _load_yaml(config_path)
        if not isinstance(services, dict):
            continue

        for service_key, raw_conf in services.items():
            if not isinstance(raw_conf, dict):
                continue
            if not (
                _is_truthy(raw_conf.get("enabled"))
                and _is_truthy(raw_conf.get("shared"))
            ):
                continue

            line = _find_service_line(config_path, service_key)
            if "bond" not in raw_conf:
                findings.append(
                    BondFinding(
                        role_dir.name,
                        service_key,
                        "bond is not set",
                        config_path,
                        line,
                    )
                )
            elif not _valid_bond(raw_conf["bond"]):
                findings.append(
                    BondFinding(
                        role_dir.name,
                        service_key,
                        f"bond={raw_conf['bond']!r} is not a number in 0..1",
                        config_path,
                        line,
                    )
                )

    findings.sort(key=lambda f: (f.role, f.service))
    return findings


def _emit_warning(finding: BondFinding, root: Path) -> None:
    rel = finding.config_path.relative_to(root).as_posix()
    warning(
        f"{finding.role}: services.{finding.service}.{finding.problem}",
        title="Missing service bond",
        file=rel,
        line=finding.line,
    )


def _print_summary(findings: list[BondFinding], root: Path) -> None:
    if not findings:
        return
    print()
    print(f"[WARNING] enabled+shared services without a valid bond ({len(findings)}):")
    for f in findings:
        rel = f.config_path.relative_to(root).as_posix()
        print(f"- {rel}:{f.line} - services.{f.service}: {f.problem} ({f.role})")


class TestServiceBond(unittest.TestCase):
    def test_enabled_shared_services_declare_bond(self) -> None:
        """Fail when an enabled + shared service is missing a valid ``bond``."""
        root = PROJECT_ROOT
        findings = _collect_findings(root)

        for finding in findings:
            _emit_warning(finding, root)

        if not in_github_actions():
            _print_summary(findings, root)

        if findings:
            lines = [
                f"{f.config_path.relative_to(root).as_posix()}:{f.line}: "
                f"services.{f.service}: {f.problem} ({f.role})"
                for f in findings
            ]
            self.fail(
                f"enabled+shared services must declare a `bond` (number in 0..1) "
                f"on {len(findings)} entries:\n" + "\n".join(lines)
            )


if __name__ == "__main__":
    unittest.main()
