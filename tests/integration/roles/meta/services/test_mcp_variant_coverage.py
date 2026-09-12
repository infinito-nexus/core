"""Every deployable MCP surface has at least one peer that can reach it.

``test_dynamic_flags.py`` exempts the ``mcp`` key from the peer-role rule,
because an MCP provider must not decide its own exposure from another role's
presence. That exemption leaves a hole: a role can declare a whole served
surface, wire its sidecar and its probe, and never enable any of it. The deploy
stays green because every gated task is skipped, so the surface looks proven
while nothing ran.

This lint closes that hole. ``mcp.enabled`` is derived from the consumer edges
in ``meta/services.yml``, so a role whose surface nobody admits resolves to a
literal ``False`` and can never run.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-variant-coverage`` in the head of a ``meta/mcp.yml``
  file exempts that role.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.applications import get_application_defaults
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.mcp import MCP_DEPLOYABLE_CLASSIFICATIONS
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

_RULE = "mcp-variant-coverage"


class TestMcpVariantCoverage(unittest.TestCase):
    """Hard lint: a declared MCP surface is reachable by some peer."""

    def test_every_deployable_mcp_block_has_an_admitted_peer(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")

        defaults = get_application_defaults(roles_dir=roles_root)
        offenders: list[str] = []

        for role_dir in sorted(p for p in roles_root.iterdir() if p.is_dir()):
            mcp_path = role_dir / ROLE_FILE_META_MCP
            if not mcp_path.is_file():
                continue
            if is_suppressed_in_head(read_text(str(mcp_path)).splitlines(), _RULE):
                continue

            mcp = load_yaml_any(str(mcp_path), default_if_missing={})
            if not isinstance(mcp, Mapping):
                continue
            if mcp.get("classification") not in MCP_DEPLOYABLE_CLASSIFICATIONS:
                continue

            block = (defaults.get(role_dir.name) or {}).get("mcp")
            resolved = block.get("enabled") if isinstance(block, Mapping) else None
            if resolved is None or resolved is False:
                offenders.append(
                    f"{role_dir.name}: no role declares itself an "
                    f"mcp_consumer this surface admits, so its adapter, probe "
                    f"and endpoint can never run"
                )

        if offenders:
            self.fail(
                f"unreachable MCP surfaces ({len(offenders)}):\n"
                + "\n".join(f"  - {o}" for o in sorted(offenders))
            )


if __name__ == "__main__":
    unittest.main()
