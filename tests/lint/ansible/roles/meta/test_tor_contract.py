"""Lint guard for the per-role tor (onion) service-block contract.

Every role that serves a domain MUST wire up the shared tor provider by
declaring a ``tor:`` block in ``meta/services.yml``. "Serves a domain" mirrors
``plugins/filter/canonical_domains_map.py``: the role name starts with
``web-``/``svc-db-`` (auto-default ``<entity>.<DOMAIN_PRIMARY>`` domain) or it
declares an explicit ``domains.canonical`` in ``meta/server.yml``. The block
controls whether the app is additionally reachable over the node onion and how:

  * ``enabled`` — present, gates onion routing for the app (typically
    ``"{{ 'svc-net-tor' in group_names }}"``).
  * ``shared`` — present; the app rides the shared node onion as a subdomain.

``exclusive`` (drop the clearnet vhost, onion only) and ``primary`` (make the
onion the app's canonical domain) are NOT required per consumer: they default
from the ``svc-net-tor`` provider's own ``tor`` block and are resolved via
``resolve_service_config`` (consumer-override -> provider-native). A consumer
MAY still declare either field to override the provider default.

The block is a shared-service reference to the ``tor`` provider (svc-net-tor),
so ``test_service_shared_consistency`` and ``test_service_bond`` additionally
require ``shared`` next to ``enabled`` and a ``bond``.

A role that serves a domain but legitimately must not ride the node onion (e.g.
a pure redirect helper with no onion surface) MAY opt out with
``# nocheck: tor-contract`` anywhere in its ``meta/services.yml``.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any

import yaml

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVER, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"
_REQUIRED_FIELDS = ("enabled", "shared")
_AUTO_DEFAULT_PREFIXES = ("web-", "svc-db-")
_RULE = "tor-contract"


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        text = read_text(str(path))
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    try:
        return load_yaml_str(text)
    except yaml.YAMLError:
        return None


def _has_canonical_domain(server: Any) -> bool:
    if not isinstance(server, dict):
        return False
    domains = server.get("domains")
    if not isinstance(domains, dict):
        return False
    canonical = domains.get("canonical")
    return bool(canonical)


def _is_present(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, str):
        return value.strip() != ""
    return value is not None


class TestTorRoleContract(unittest.TestCase):
    def test_domain_roles_declare_tor_block(self) -> None:
        violations: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            if not role_dir.is_dir():
                continue
            role_name = role_dir.name
            server = _load_yaml(role_dir / ROLE_FILE_META_SERVER)
            if not (
                role_name.startswith(_AUTO_DEFAULT_PREFIXES)
                or _has_canonical_domain(server)
            ):
                continue
            if role_name == "svc-net-tor":
                continue

            services_path = role_dir / ROLE_FILE_META_SERVICES
            if services_path.is_file() and any(
                line_has_rule(line, _RULE)
                for line in read_text(str(services_path)).splitlines()
            ):
                continue

            services = _load_yaml(services_path)
            if not isinstance(services, dict):
                violations.append(
                    f"{role_name}: has domains.canonical but no readable "
                    f"meta/services.yml to declare the tor block."
                )
                continue
            tor = services.get("tor")
            if not isinstance(tor, dict):
                violations.append(
                    f"{role_name}: has domains.canonical but no `tor:` block in "
                    f"meta/services.yml."
                )
                continue
            violations.extend(
                f"{role_name}: meta/services.yml.tor.{field} is missing or empty."
                for field in _REQUIRED_FIELDS
                if field not in tor or not _is_present(tor.get(field))
            )

        if violations:
            self.fail(
                "Roles serving a domain must declare a complete tor service "
                "block:\n"
                + "\n".join(f"  - {v}" for v in violations)
                + "\n\nAdd to the role's meta/services.yml (exclusive/primary "
                + "default from the svc-net-tor provider):\n"
                + "  tor:\n"
                + "    bond: 1\n"
                + "    enabled: \"{{ 'svc-net-tor' in group_names }}\"\n"
                + "    shared: true  # nocheck: dynamic-flag\n"
            )


if __name__ == "__main__":
    unittest.main()
