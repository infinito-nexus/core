"""Every deployable MCP surface is switched on by at least one variant.

``test_dynamic_flags.py`` exempts the ``mcp`` key from the peer-role rule,
because an MCP provider must not decide its own exposure from another role's
presence. That exemption is what makes the "``false`` in ``meta/services.yml``,
``true`` in variant 0" pattern legal, and it leaves a hole: a role can declare a
whole served surface, wire its sidecar and its probe, and never enable any of
it. The deploy stays green because every gated task is skipped, so the surface
looks proven while nothing ran.

This lint closes that hole. A role that declares a deployable ``mcp`` block MUST
have a variant that turns it on.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-variant-coverage`` in the head of a ``meta/services.yml``
  file exempts that role.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.mcp import MCP_DEPLOYABLE_CLASSIFICATIONS
from utils.roles.mapping import ROLE_FILE_META_MCP, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

_RULE = "mcp-variant-coverage"


class TestMcpVariantCoverage(unittest.TestCase):
    """Hard lint: a declared MCP surface is reachable in some variant."""

    def test_every_deployable_mcp_block_is_enabled_by_a_variant(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")

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
            if mcp.get("enabled") is True:
                continue

            variants_path = role_dir / ROLE_FILE_META_VARIANTS
            if not variants_path.is_file():
                offenders.append(
                    f"{role_dir.name}: mcp is off in meta/services.yml "
                    f"and the role ships no meta/variants.yml, so its adapter, "
                    f"probe and endpoint can never run"
                )
                continue

            variants = load_yaml_any(str(variants_path), default_if_missing=[])
            enabled = any(
                ((variant or {}).get("mcp") or {}).get("enabled") is True
                for variant in variants or []
                if isinstance(variant, Mapping)
            )
            if not enabled:
                offenders.append(
                    f"{role_dir.name}: mcp is off in meta/services.yml "
                    f"and no variant enables it, so its adapter, probe and "
                    f"endpoint can never run"
                )

        if offenders:
            self.fail(
                f"unreachable MCP surfaces ({len(offenders)}):\n"
                + "\n".join(f"  - {o}" for o in sorted(offenders))
            )


if __name__ == "__main__":
    unittest.main()
