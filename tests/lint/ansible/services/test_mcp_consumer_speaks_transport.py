"""Lint: a provider only admits consumers that can speak its transport.

Admission and ``supported_transports`` are declared in different
files by different people, and nothing made them agree. Admitting a client that
cannot speak the provider's transport is not a narrowing decision: discovery
classifies it ``transport_unsupported``, which is fatal, so the pair aborts
every deployment that happens to contain both roles.

Flowise at its pinned release is the case this was written for. It reaches an
MCP server over Streamable HTTP only; pointed at an SSE endpoint the toolkit
falls back and the SDK rejects the response body with ``expected a web
ReadableStream``. Admitting it to an SSE provider therefore cannot work, and the
declaration is where that has to be caught.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-consumer-transport`` in the head of the provider's ``meta/mcp.yml``.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.mcp import (
    DEFAULT_MCP_TRANSPORT,
    derive_allowed_consumers,
)
from utils.roles.mapping import ROLE_FILE_META_MCP, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "mcp-consumer-transport"
_SERVER_DIRECTIONS = frozenset({"server", "both"})


def _blocks() -> dict[str, Mapping]:
    """Return every role's MCP block, keyed by role name."""
    blocks = {}
    for path in sorted(Path(PROJECT_ROOT, "roles").glob(f"*/{ROLE_FILE_META_MCP}")):
        block = load_yaml_any(str(path), default_if_missing={})
        if isinstance(block, Mapping):
            blocks[path.parent.parent.name] = block
    return blocks


def _services_by_role() -> dict[str, object]:
    """Return every role's services mapping, keyed by role name."""
    return {
        path.parent.parent.name: load_yaml_any(str(path), default_if_missing={})
        for path in sorted(
            Path(PROJECT_ROOT, "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")
        )
    }


def mismatched_pairs() -> list[str]:
    """Return one finding per provider admitting a transport-incompatible client."""
    blocks = _blocks()
    services_by_role = _services_by_role()
    findings = []
    for role, block in blocks.items():
        if str(block.get("direction") or "").strip().lower() not in _SERVER_DIRECTIONS:
            continue
        path = Path(PROJECT_ROOT, "roles", role, ROLE_FILE_META_MCP)
        if is_suppressed_in_head(read_text(str(path)).splitlines(), _RULE):
            continue

        transport = str(block.get("transport") or DEFAULT_MCP_TRANSPORT)
        for consumer in derive_allowed_consumers(role, services_by_role):
            spoken = (blocks.get(str(consumer)) or {}).get("supported_transports")
            if not spoken:
                continue
            if transport in {str(entry) for entry in spoken}:
                continue
            findings.append(
                f"{role}: admits {consumer!r}, but serves {transport!r} while "
                f"that client speaks {sorted(str(e) for e in spoken)}"
            )
    return findings


class TestMcpConsumerSpeaksTransport(unittest.TestCase):
    def test_every_admitted_consumer_speaks_the_provider_transport(self) -> None:
        findings = mismatched_pairs()
        self.assertEqual(
            [],
            findings,
            f"MCP pair(s) that cannot connect ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_finds_admitted_consumers(self) -> None:
        services_by_role = _services_by_role()
        admitted = [
            role
            for role in _blocks()
            if derive_allowed_consumers(role, services_by_role)
        ]
        self.assertTrue(
            admitted,
            "no provider admits a consumer, so the rule would pass vacuously",
        )


if __name__ == "__main__":
    unittest.main()
