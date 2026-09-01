"""Lint: an enabled MCP provider proves its declared credential against itself.

``auth_subject`` and ``credential.owner`` are declarations. Nothing stops a role
from declaring one principal and provisioning another, and a client would then
discover an endpoint whose credential belongs to nobody, or worse to an account
with more rights than the block admits.

Every provider closes that gap the same way: it includes
``roles/svc-ai-mcp-adapter/tasks/probe.yml``, which resolves
``mcp.credential.owner`` from the declaration, renders the header a client would
send, and calls the live endpoint. A provider that skips the probe has a
documentation-only identity.

Disabled providers are exempt: they serve nothing, so there is nothing to prove
until an operator turns them on.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-provider-probe`` in the head of the role's ``meta/mcp.yml``.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.applications import get_application_defaults
from utils.cache.files import iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

_RULE = "mcp-provider-probe"
_SERVER_DIRECTIONS = frozenset({"server", "both"})
_PROBE = "roles/svc-ai-mcp-adapter/tasks/probe.yml"


def _enabled_providers() -> list[Path]:
    """Return the role directories serving an MCP endpoint right now."""
    roles_root = Path(PROJECT_ROOT, "roles")
    defaults = get_application_defaults(roles_dir=roles_root)
    roles: list[Path] = []
    for mcp_path in sorted(roles_root.glob(f"*/{ROLE_FILE_META_MCP}")):
        mcp = load_yaml_any(str(mcp_path), default_if_missing={})
        if not isinstance(mcp, Mapping):
            continue
        if str(mcp.get("direction") or "").strip().lower() not in _SERVER_DIRECTIONS:
            continue
        role_dir = mcp_path.parent.parent
        block = (defaults.get(role_dir.name) or {}).get("mcp")
        resolved = block.get("enabled") if isinstance(block, Mapping) else None
        if not resolved:
            continue
        if is_suppressed_in_head(read_text(str(mcp_path)).splitlines(), _RULE):
            continue
        roles.append(role_dir)
    return roles


def _roles_including_the_probe() -> set[str]:
    """Return the role names whose task tree pulls in the shared probe."""
    including: set[str] = set()
    for path, content in iter_project_files_with_content(extensions=(".yml",)):
        if _PROBE not in content:
            continue
        parts = Path(path).parts
        if "roles" in parts and "tasks" in parts:
            including.add(parts[parts.index("roles") + 1])
    return including


class TestMcpProviderProbe(unittest.TestCase):
    def test_every_enabled_provider_probes_its_declared_credential(self) -> None:
        including = _roles_including_the_probe()
        missing = [
            f"{role.name}: serves MCP but never includes {_PROBE}, so its "
            f"declared credential owner is never proven against the endpoint"
            for role in _enabled_providers()
            if role.name not in including
        ]
        self.assertEqual(
            [],
            missing,
            f"MCP provider(s) with an unproven identity ({len(missing)}):\n"
            + "\n".join(f"  - {m}" for m in missing),
        )

    def test_the_scan_finds_enabled_providers(self) -> None:
        self.assertTrue(
            _enabled_providers(),
            "no MCP block declares an enabled server, so the rule would pass "
            "vacuously; check that the scan still reads the right topic",
        )


if __name__ == "__main__":
    unittest.main()
