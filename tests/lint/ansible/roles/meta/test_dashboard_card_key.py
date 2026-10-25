"""Lint guard for the dashboard card target a role names in ``meta/services.yml``.

A role MAY point its dashboard card at a non-primary domain by naming
``card: <key>`` on its ``dashboard`` binding. The key MUST be a key of the
role's ``meta/domains.yml`` ``canonical`` mapping, the only keys
``lookup('canonical_url', <role>, <key>)`` resolves.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any

import yaml
from ansible.errors import AnsibleError

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.applications.dashboard import (
    CARD_TARGET_KEY,
    DASHBOARD_SERVICE,
    card_target_key,
)
from utils.roles.mapping import ROLE_FILE_META_DOMAINS, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return load_yaml_str(read_text(str(path)))
    except (UnicodeDecodeError, yaml.YAMLError):
        return None


def _card_key_violation(role_dir: Path) -> str | None:
    role_name = role_dir.name
    services = _load_yaml(role_dir / ROLE_FILE_META_SERVICES)
    if not isinstance(services, dict):
        return None
    try:
        key = card_target_key(role_name, services.get(DASHBOARD_SERVICE))
    except AnsibleError as exc:
        return str(exc)
    if not key:
        return None
    domains = _load_yaml(role_dir / ROLE_FILE_META_DOMAINS)
    canonical = domains.get("canonical") if isinstance(domains, dict) else None
    if not isinstance(canonical, dict) or key not in canonical:
        available = sorted(canonical) if isinstance(canonical, dict) else []
        return (
            f"{role_name}: services.{DASHBOARD_SERVICE}.{CARD_TARGET_KEY} '{key}' "
            f"is not a key of {ROLE_FILE_META_DOMAINS} canonical "
            f"(available: {available})."
        )
    return None


class TestDashboardCardKey(unittest.TestCase):
    def test_card_key_is_a_domain_key_of_its_role(self) -> None:
        violations = [
            violation
            for role_dir in sorted(ROLES_DIR.iterdir())
            if role_dir.is_dir()
            and (violation := _card_key_violation(role_dir)) is not None
        ]
        if violations:
            self.fail(
                f"A dashboard binding's `{CARD_TARGET_KEY}` MUST name a "
                "domains.canonical key of its own role:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )


if __name__ == "__main__":
    unittest.main()
