"""A surface that serves mutating tools has to name them.

``mutating_tools_enabled: false`` is a claim, not a mechanism. Where the
upstream cannot scope the credential it issues, nothing refuses the call, and
the only remaining boundary is the include list every client renders. That list
is built by subtracting ``tools.mutating`` from ``tools.allowlist``, so a
mutating tool that is served but not named is offered to every client while the
declaration says mutations are off.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-mutating-tools-named`` in the head of the role's
  ``meta/mcp.yml``.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

_RULE = "mcp-mutating-tools-named"
_SERVING = {"server", "both"}


def _surfaces() -> list[tuple[str, Mapping]]:
    """Return ``(role, mcp block)`` for every role declaring an MCP surface."""
    found = []
    for path in sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_MCP}")):
        if is_suppressed_in_head(read_text(str(path)).splitlines(), _RULE):
            continue
        block = load_yaml_any(str(path), default_if_missing={})
        if isinstance(block, Mapping):
            found.append((path.parent.parent.name, block))
    return found


class TestMcpMutatingToolsNamed(unittest.TestCase):
    def test_named_mutating_tools_are_part_of_the_allowlist(self) -> None:
        stray = []
        for role, block in _surfaces():
            tools = block.get("tools")
            if not isinstance(tools, Mapping):
                continue
            allowlist = set(tools.get("allowlist") or [])
            outside = sorted(set(tools.get("mutating") or []) - allowlist)
            if outside:
                stray.append(
                    f"{role}: names {outside} as mutating, but the allowlist "
                    f"does not serve them, so the subtraction removes nothing "
                    f"and the name is stale"
                )
        self.assertEqual(
            [],
            stray,
            "mutating name(s) outside the served set:\n"
            + "\n".join(f"  - {s}" for s in stray),
        )

    def test_a_surface_that_permits_mutations_names_none(self) -> None:
        contradictory = []
        for role, block in _surfaces():
            tools = block.get("tools")
            if not isinstance(tools, Mapping):
                continue
            if tools.get("mutating_tools_enabled") and tools.get("mutating"):
                contradictory.append(
                    f"{role}: permits mutations yet still names {sorted(tools['mutating'])} "
                    f"as withheld; a reader cannot tell which half is meant"
                )
        self.assertEqual(
            [],
            contradictory,
            "surface(s) both permitting and withholding mutation:\n"
            + "\n".join(f"  - {c}" for c in contradictory),
        )

    def test_the_scan_finds_surfaces(self) -> None:
        self.assertTrue(
            [role for role, block in _surfaces() if block.get("direction") in _SERVING],
            "no serving MCP surface was read, so every rule here would pass "
            "vacuously; check that the scan still reaches the roles' MCP "
            "declarations",
        )


if __name__ == "__main__":
    unittest.main()
