"""Integration guard: an MCP provider ships one round that is only MCP.

A provider's clients cost a full application stack each, so the round that
proves the MCP pairing must not also carry the role's SSO, mail, metrics and
dashboard surfaces. Every role with a ``meta/mcp.yml`` that admits at least
one consumer therefore needs one variant that is exactly that pairing:

* every admitted consumer pinned ``enabled: true`` with ``services: null``,
  so the client is deployed but drags none of its own dependencies along,
* every other service pinned ``enabled: false``.

``tor`` is exempt because the onion round is a deploy axis rather than a
feature of the role, ``litellm`` because the gateway is what the clients
answer prompts through, and so are the role's own entity and any service its
``meta/services.yml`` pins to a literal ``true`` — the datastores, which a
variant cannot switch off without taking the application with them.

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
_ALWAYS_ALLOWED = frozenset({"tor", "litellm"})

ROLES_DIR = PROJECT_ROOT / "roles"


def _statically_on(base_services: Mapping) -> set[str]:
    """Return service keys a variant cannot switch off.

    Args:
        base_services: the role's ``meta/services.yml`` mapping.

    A literal ``enabled: true`` in the base is the datastore shape: it states
    a fact about what the application needs, not a per-round choice.
    """
    return {
        key
        for key, entry in base_services.items()
        if isinstance(entry, Mapping) and entry.get("enabled") is True
    }


def _variant_findings(
    role: str, consumers: set[str], variant: Mapping, allowed: set[str]
) -> list[str]:
    """Return why one variant is not the role's MCP-only round.

    Args:
        role: the provider role id.
        consumers: entity keys of every admitted consumer.
        variant: one ``meta/variants.yml`` entry.
        allowed: keys that may stay on besides the consumers.
    """
    services = variant.get("services")
    if not isinstance(services, Mapping):
        return [f"{role}: variant declares no services"]
    findings: list[str] = []
    for key in sorted(consumers):
        entry = services.get(key)
        if not isinstance(entry, Mapping) or entry.get("enabled") is not True:
            findings.append(f"{role}: {key} is not enabled")
        elif "services" not in entry or entry["services"] is not None:
            findings.append(f"{role}: {key} lacks `services: null`")
    findings.extend(
        f"{role}: {key} stays enabled"
        for key, entry in sorted(services.items())
        if isinstance(entry, Mapping)
        and entry.get("enabled") is True
        and key not in consumers
        and key not in allowed
    )
    return findings


def offenders() -> list[str]:
    """Return one finding per provider without an MCP-only variant."""
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
        base = services_by_role.get(role)
        allowed = (
            _ALWAYS_ALLOWED
            | {get_entity_name(role)}
            | (_statically_on(base) if isinstance(base, Mapping) else set())
        )
        per_variant = [
            _variant_findings(role, consumers, v, allowed)
            for v in variants.get(role, [])
            if isinstance(v, Mapping)
        ]
        if any(not f for f in per_variant):
            continue
        closest = min(per_variant, key=len) if per_variant else [f"{role}: no variants"]
        findings.append(
            f"{role}: no variant is the MCP-only round; the closest one still "
            f"reports: {'; '.join(closest)}"
        )
    return findings


class TestMcpConsumerVariant(unittest.TestCase):
    def test_every_provider_ships_an_mcp_only_variant(self) -> None:
        findings = offenders()
        self.assertEqual(
            [],
            findings,
            f"MCP provider(s) without an MCP-only variant ({len(findings)}):\n"
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
