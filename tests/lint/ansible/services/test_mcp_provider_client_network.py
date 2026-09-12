"""Lint: an MCP provider opens a network the clients it admits can join.

``mcp_servers`` hands every client the bare URL
``http://<endpoint.service_key>:<port><path>``. That name only resolves when the
client shares a network with the provider, which is what
``meta/networks.yml.overlay`` arranges: a ``topology`` creates the network and
``consumer.kind: mcp_client`` attaches every role the provider admits through
the ``mcp_consumer`` flag. A beacon-only overlay carries neither, so
``utils.networks.attachments._compute_attachments`` produces no attachment at
all.

Nothing fails when that happens. The docker daemon ships
``dns-search: [DOMAIN_PRIMARY]``, so the unresolvable service name is completed
into a public FQDN, the wildcard record answers with the ingress address, and
the client talks to the reverse proxy over the internet instead of to the
container next door. The tool calls still succeed, which is why this survives a
deploy: only the route is wrong.

``web-app-wordpress`` was this exact shape and sent every MCP call for its
Apache container out through the public ingress.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-provider-client-network`` in the head of the provider's
  ``meta/networks.yml``.
"""

from __future__ import annotations

import unittest

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP, ROLE_FILE_META_NETWORKS

from . import PROJECT_ROOT

_RULE = "mcp-provider-client-network"
_CLIENT_KIND = "mcp_client"


def consumer_kinds(overlay: dict) -> list[str]:
    """Return the consumer kinds an overlay declares, always as a list.

    Args:
        overlay: the ``overlay`` mapping of a role's ``meta/networks.yml``.
    """
    declared = (overlay.get("consumer") or {}).get("kind") or "services_flags"
    return [
        str(kind) for kind in (declared if isinstance(declared, list) else [declared])
    ]


def unreachable_providers() -> list[str]:
    findings: list[str] = []
    for meta in sorted(PROJECT_ROOT.glob(f"roles/*/{ROLE_FILE_META_MCP}")):
        block = load_yaml_any(str(meta), default_if_missing={})
        if not isinstance(block, dict) or not block.get("endpoint"):
            continue
        role = meta.parent.parent
        networks = role / ROLE_FILE_META_NETWORKS
        if is_suppressed_in_head(
            read_text(str(networks)).splitlines() if networks.exists() else [], _RULE
        ):
            continue
        loaded = load_yaml_any(str(networks), default_if_missing={})
        overlay = (loaded or {}).get("overlay") if isinstance(loaded, dict) else None
        if not isinstance(overlay, dict) or not overlay.get("topology"):
            findings.append(
                f"{role.name}: overlay declares no topology, so no network exists to join"
            )
            continue
        if _CLIENT_KIND not in consumer_kinds(overlay):
            findings.append(
                f"{role.name}: overlay admits {consumer_kinds(overlay)}, never {_CLIENT_KIND!r}"
            )
    return findings


class TestMcpProviderClientNetwork(unittest.TestCase):
    def test_every_mcp_endpoint_provider_attaches_its_clients(self) -> None:
        findings = unreachable_providers()
        self.assertEqual(
            [],
            findings,
            f"MCP providers whose clients cannot resolve the endpoint service name "
            f"({len(findings)}); the dns-search suffix routes those calls through the "
            f"public ingress instead, and the call still succeeds:\n"
            + "\n".join(f"  - {entry}" for entry in findings),
        )


if __name__ == "__main__":
    unittest.main()
