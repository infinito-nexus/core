"""Lint: an MCP provider carries a services entry for every declared client.

A client declares itself once, in its own ``meta/services.yml`` self-entry,
as ``mcp_consumer: true``. Every server-capable ``meta/mcp.yml`` MUST then
carry a matching ``services.<client-entity>`` entry whose ``enabled`` and
``shared`` resolve through the ``"{{ '<role>' in group_names }}"`` form.

Two things depend on that entry. The inventory resolver builds a round's
co-deploy closure from services edges alone, so without it a provider is
never planned together with a client and its MCP surface is never exercised
end to end. The network layer admits a client to the provider's overlay
through the same entry.

Admission itself is NOT what the entry decides: a provider that must refuse
a client adds ``mcp_consumer: false`` to that entry. Keeping the entry and
spelling the refusal out is what makes a deliberate exclusion
distinguishable from a forgotten one.

Add ``# nocheck: mcp-consumer-services-entry`` to the head of the provider's
``meta/mcp.yml`` for one that legitimately owns no such edge.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.mcp import (
    MCP_CONSUMER_FLAG,
    declares_mcp_consumer,
)
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_MCP, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "mcp-consumer-services-entry"
_SERVER_DIRECTIONS = frozenset({"server", "both"})


def _services_by_role() -> dict[str, Mapping]:
    services = {}
    for path in sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")):
        loaded = load_yaml_any(str(path), default_if_missing={})
        if isinstance(loaded, Mapping):
            services[path.parent.parent.name] = loaded
    return services


def _gates_on(value: object, role_id: str) -> bool:
    return isinstance(value, str) and f"'{role_id}' in group_names" in value


def missing_entries() -> list[str]:
    """Return one finding per provider missing a declared client's entry."""
    services_by_role = _services_by_role()
    consumers = [
        role_id
        for role_id, services in services_by_role.items()
        if declares_mcp_consumer(role_id, services)
    ]

    findings: list[str] = []
    for meta in sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_MCP}")):
        role = meta.parent.parent.name
        block = load_yaml_any(str(meta), default_if_missing={})
        if not isinstance(block, Mapping):
            continue
        if str(block.get("direction") or "").strip().lower() not in _SERVER_DIRECTIONS:
            continue
        if is_suppressed_in_head(read_text(str(meta)).splitlines(), _RULE):
            continue

        services = services_by_role.get(role) or {}
        for consumer in consumers:
            if consumer == role:
                continue
            key = get_entity_name(consumer)
            entry = services.get(key)
            if not isinstance(entry, Mapping):
                findings.append(
                    f"{role}: no 'services.{key}' entry for the declared MCP "
                    f"client {consumer!r}; add one gated on "
                    f"\"{{{{ '{consumer}' in group_names }}}}\", with "
                    f"'{MCP_CONSUMER_FLAG}: false' if it must not be admitted"
                )
                continue
            findings.extend(
                f"{role}: services.{key}.{flag} must gate on "
                f"\"{{{{ '{consumer}' in group_names }}}}\" so the "
                f"round plans provider and client together"
                for flag in ("enabled", "shared")
                if not _gates_on(entry.get(flag), consumer)
            )
    return findings


class TestMcpConsumerServicesEntry(unittest.TestCase):
    def test_every_provider_declares_every_client(self) -> None:
        findings = missing_entries()
        self.assertEqual(
            [],
            findings,
            f"MCP provider(s) missing a client services entry ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_finds_declared_clients(self) -> None:
        services_by_role = _services_by_role()
        declared = [
            role_id
            for role_id, services in services_by_role.items()
            if declares_mcp_consumer(role_id, services)
        ]
        self.assertTrue(
            declared,
            "no role declares mcp_consumer, so the rule would pass vacuously",
        )


if __name__ == "__main__":
    unittest.main()
