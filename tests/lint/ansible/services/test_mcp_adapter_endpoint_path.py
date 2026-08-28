"""Lint: an adapter provider declares the path its adapter actually serves.

The adapter answers exactly one path, and every provider that runs behind it
declares its own ``endpoint.path``. That is the same fact in two files. When they
drift, nothing fails at deploy time: the adapter starts, the client registers the
declared URL, and the mismatch only shows up as a 404 on the first tool call,
which reads like an upstream problem rather than a declaration error.

The transport of ``web-app-flowise`` was this exact shape - a hard-coded constant
disagreeing with ``meta/mcp.yml`` - and cost three deploys before the runtime
settled it.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-adapter-endpoint-path`` in the head of the provider's ``meta/mcp.yml``.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

_RULE = "mcp-adapter-endpoint-path"
_ADAPTER_SERVER = PROJECT_ROOT / "roles/svc-ai-mcp-adapter/files/python/server.py"
_ENDPOINT_CONST = re.compile(r'^ENDPOINT\s*=\s*"([^"]+)"', re.MULTILINE)


def served_endpoint() -> str:
    match = _ENDPOINT_CONST.search(read_text(str(_ADAPTER_SERVER)))
    if not match:
        raise AssertionError(
            f"{_ADAPTER_SERVER.name} no longer defines ENDPOINT; this lint reads it "
            f"to compare against every adapter provider's declared path"
        )
    return match.group(1)


def drifting_providers() -> list[str]:
    expected = served_endpoint()
    findings: list[str] = []
    for meta in sorted(PROJECT_ROOT.glob(f"roles/*/{ROLE_FILE_META_MCP}")):
        block = load_yaml_any(str(meta), default_if_missing={})
        if not isinstance(block, dict):
            continue
        if str(block.get("implementation") or "").strip() != "adapter":
            continue
        declared = str((block.get("endpoint") or {}).get("path") or "").strip()
        if declared == expected:
            continue
        if is_suppressed_in_head(read_text(str(meta)).splitlines(), _RULE):
            continue
        findings.append(
            f"{meta.parent.parent.name}: declares {declared!r} while the adapter "
            f"serves {expected!r}"
        )
    return findings


class TestMcpAdapterEndpointPath(unittest.TestCase):
    def test_every_adapter_provider_declares_the_served_path(self) -> None:
        findings = drifting_providers()
        self.assertEqual(
            [],
            findings,
            f"adapter providers whose declared path is not served ({len(findings)}); "
            f"the mismatch surfaces as a 404 on the first tool call, not at deploy:\n"
            + "\n".join(f"  - {entry}" for entry in findings),
        )


if __name__ == "__main__":
    unittest.main()
