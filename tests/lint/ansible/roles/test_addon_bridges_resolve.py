"""Every ``bridges:`` value on an addon must name a declared service.

Rationale
=========
``plugins/lookup/addon_env_flags.py`` turns an addon's ``bridges:`` list into
its Playwright gate flag: a required addon is announced as enabled only when a
bridged partner is part of the run. A bridge therefore names a **service** —
``sso``, ``ldap``, ``coturn``, ``talk`` — and the lookup maps that service to
the role carrying it.

A value no ``meta/services.yml`` declares can never map to anything. It is not
a strict gate but an off switch: ``_any_bridge_partner_deployed`` returns False
for every run, the flag is ``false`` everywhere, and ``skipUnlessAddonEnabled``
skips that spec in every variant. Nothing fails, the suite just quietly stops
testing the addon.

This lint checks the name exists. Whether a given run deploys the service is a
runtime question the lookup answers.
"""

from __future__ import annotations

import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_ADDONS_GLOB = "*/meta/addons/*.yml"
_SERVICES_GLOB = f"*/{ROLE_FILE_META_SERVICES}"


def _declared_services() -> set[str]:
    names: set[str] = set()
    for path in sorted((PROJECT_ROOT / "roles").glob(_SERVICES_GLOB)):
        services = load_yaml_any(path) or {}
        if not isinstance(services, dict):
            continue
        names.update(
            str(key) for key, entry in services.items() if isinstance(entry, dict)
        )
    return names


def _item_line(lines: list[str], value: str) -> int:
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        if stripped[2:].split("#", 1)[0].strip().strip("\"'") == value:
            return line_no
    return 0


def _undeclared_bridges(declared: set[str]) -> list[str]:
    findings: list[str] = []
    for path in sorted((PROJECT_ROOT / "roles").glob(_ADDONS_GLOB)):
        spec = load_yaml_any(path) or {}
        bridges = spec.get("bridges") if isinstance(spec, dict) else None
        if not isinstance(bridges, list):
            continue
        lines = read_text(str(path)).splitlines()
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        findings.extend(
            f"{rel}:{_item_line(lines, bridge)}: bridges: {bridge!r}"
            for bridge in (str(raw).strip() for raw in bridges)
            if bridge and bridge not in declared
        )
    return findings


class TestAddonBridgesResolve(unittest.TestCase):
    def test_every_bridge_names_a_declared_service(self) -> None:
        findings = _undeclared_bridges(_declared_services())

        self.assertFalse(
            findings,
            f"{len(findings)} addon bridge(s) name a service that no "
            "meta/services.yml declares, so their gate flag is false in every "
            "variant and the spec never runs. Use the service key as it appears "
            "in the carrying role's meta/services.yml — 'sso' for "
            "web-app-keycloak, 'talk' for the container inside "
            "web-app-nextcloud:\n" + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
