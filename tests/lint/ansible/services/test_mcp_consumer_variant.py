"""Lint: an MCP provider ships a round that proves the pairing.

A surface nobody deploys against is never exercised, so every role with a
``meta/mcp.yml`` that admits at least one consumer needs one variant pinning
every admitted consumer to ``enabled: true``.

That round also has to be able to sign in. An MCP client spec signs in through
the client's own OIDC button, which redirects to Keycloak, so a round without
an identity provider skips the lot and proves nothing it was built to prove.
The provider
therefore keeps ``sso`` on in that variant, and so does each consumer in the
variant the round actually pulls in: a round deploys every dependency at its
own index, falling back to variant 0 when it has fewer, so the client that
ships alongside is that one and not the client's variant 0.

A role that declares no ``sso`` service, or pins it to a literal ``false``
because upstream speaks no OIDC, is exempt from the flag it cannot have.

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


def _declares_sso(services: Mapping | None) -> bool:
    """Whether a role can put an identity provider in front of itself.

    A literal ``enabled: false`` is the shape a role uses when upstream
    speaks no OIDC at all, so there is nothing for a variant to pin on.
    """
    if not isinstance(services, Mapping):
        return False
    entry = services.get("sso")
    return isinstance(entry, Mapping) and entry.get("enabled") is not False


def _sso_flag(variant: Mapping | None) -> object:
    """Return a variant's ``services.sso.enabled`` pin, or None when unpinned."""
    services = (variant or {}).get("services")
    if not isinstance(services, Mapping):
        return None
    entry = services.get("sso")
    return entry.get("enabled") if isinstance(entry, Mapping) else None


def _round_variant(variants: list, index: int) -> Mapping | None:
    """Return the entry a round at ``index`` deploys a role at.

    Args:
        variants: that role's ``meta/variants.yml`` entries.
        index: the round index the provider's variant sits at.

    A round pins every dependency to its own index and falls back to variant 0
    when the dependency has fewer, which is what
    :mod:`cli.administration.deploy.development.inventory` plans.
    """
    if not variants:
        return None
    entry = variants[index] if index < len(variants) else variants[0]
    return entry if isinstance(entry, Mapping) else None


def _variant_findings(
    role: str,
    consumers: set[str],
    variant: Mapping,
    index: int,
    services_by_role: Mapping,
    variants_by_role: Mapping,
    consumer_ids: Mapping,
) -> list[str]:
    """Return why one variant does not prove the role's MCP pairing.

    Args:
        role: the provider role id.
        consumers: entity keys of every admitted consumer.
        variant: one ``meta/variants.yml`` entry.
        index: that entry's position, which is the round index.
        services_by_role: every role's services mapping.
        variants_by_role: every role's variant list.
        consumer_ids: entity key to consumer role id.
    """
    services = variant.get("services")
    if not isinstance(services, Mapping):
        return [f"{role}: variant declares no services"]
    findings: list[str] = []
    for key in sorted(consumers):
        entry = services.get(key)
        if not isinstance(entry, Mapping) or entry.get("enabled") is not True:
            findings.append(f"{role}: {key} is not enabled")
    if findings:
        return findings

    if _declares_sso(services_by_role.get(role)) and _sso_flag(variant) is not True:
        findings.append(f"{role}: variant {index} does not pin sso on")
    for key in sorted(consumers):
        consumer = consumer_ids.get(key)
        if not consumer or not _declares_sso(services_by_role.get(consumer)):
            continue
        pulled = _round_variant(variants_by_role.get(consumer) or [], index)
        if _sso_flag(pulled) is False:
            findings.append(
                f"{role}: {key} ships with sso off in the variant round "
                f"{index} pulls in, so its MCP specs skip"
            )
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
        consumer_ids = {
            get_entity_name(c): c
            for c in derive_allowed_consumers(role, services_by_role)
        }
        consumers = set(consumer_ids)
        if not consumers:
            continue
        per_variant = [
            _variant_findings(
                role, consumers, v, index, services_by_role, variants, consumer_ids
            )
            for index, v in enumerate(variants.get(role, []))
            if isinstance(v, Mapping)
        ]
        if any(not f for f in per_variant):
            continue
        closest = (
            min(
                per_variant,
                key=lambda f: (sum("is not enabled" in x for x in f), len(f)),
            )
            if per_variant
            else [f"{role}: no variants"]
        )
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
