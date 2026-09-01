"""Integration guard: an MCP provider ships a round that proves the pairing.

A surface nobody deploys against is never exercised, so every role with a
``meta/mcp.yml`` that admits at least one consumer needs one variant pinning
every admitted consumer to ``enabled: true``. What else that variant carries
is the role's own call.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-consumer-variant`` in the head of the role's
  ``meta/mcp.yml``.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.applications import get_application_defaults, get_variants
from utils.cache.files import read_text
from utils.roles.applications.mcp import derive_allowed_consumers
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

_RULE = "mcp-consumer-variant"
_SERVER_DIRECTIONS = frozenset({"server", "both"})

ROLES_DIR = PROJECT_ROOT / "roles"


def _variant_findings(role: str, consumers: set[str], variant: Mapping) -> list[str]:
    """Return why one variant does not prove the role's MCP pairing.

    Args:
        role: the provider role id.
        consumers: entity keys of every admitted consumer.
        variant: one ``meta/variants.yml`` entry.
    """
    services = variant.get("services")
    if not isinstance(services, Mapping):
        return [f"{role}: variant declares no services"]
    findings: list[str] = []
    for key in sorted(consumers):
        entry = services.get(key)
        if not isinstance(entry, Mapping) or entry.get("enabled") is not True:
            findings.append(f"{role}: {key} is not enabled")
    return findings


def offenders() -> list[str]:
    """Return one finding per provider that never deploys its consumers."""
    defaults = get_application_defaults(roles_dir=ROLES_DIR)
    services_by_role = {
        role: (config or {}).get("services")
        for role, config in defaults.items()
        if isinstance(config, dict)
    }
    variants = get_variants(roles_dir=ROLES_DIR)
    findings: list[str] = []
    for meta in sorted(ROLES_DIR.glob(f"*/{ROLE_FILE_META_MCP}")):
        role = meta.parent.parent.name
        block = (defaults.get(role) or {}).get("mcp")
        if not isinstance(block, Mapping):
            continue
        if str(block.get("direction") or "").strip().lower() not in _SERVER_DIRECTIONS:
            continue
        if is_suppressed_in_head(read_text(str(meta)).splitlines(), _RULE):
            continue
        consumers = {
            get_entity_name(c) for c in derive_allowed_consumers(role, services_by_role)
        }
        if not consumers:
            continue
        per_variant = [
            _variant_findings(role, consumers, v)
            for v in variants.get(role, [])
            if isinstance(v, Mapping)
        ]
        if any(not f for f in per_variant):
            continue
        closest = min(per_variant, key=len) if per_variant else [f"{role}: no variants"]
        findings.append(
            f"{role}: no variant enables every admitted consumer; the closest "
            f"one still reports: {'; '.join(closest)}"
        )
    return findings


class TestMcpConsumerVariant(unittest.TestCase):
    def test_every_provider_ships_a_variant_enabling_its_consumers(self) -> None:
        findings = offenders()
        self.assertEqual(
            [],
            findings,
            f"MCP provider(s) whose consumers never deploy ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_finds_providers(self) -> None:
        defaults = get_application_defaults(roles_dir=ROLES_DIR)
        seen = sum(
            1
            for meta in ROLES_DIR.glob(f"*/{ROLE_FILE_META_MCP}")
            if isinstance(
                (defaults.get(meta.parent.parent.name) or {}).get("mcp"), Mapping
            )
        )
        self.assertTrue(
            seen,
            "no role ships meta/mcp.yml, so the rule would pass vacuously",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
