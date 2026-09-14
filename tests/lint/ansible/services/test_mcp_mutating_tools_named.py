"""A surface that serves mutating tools has to name them.

``mutating_tools_enabled: false`` is a claim, not a mechanism. Where the
upstream cannot scope the credential it issues, nothing refuses the call, and
the only remaining boundary is the include list every client renders. That list
is built by subtracting ``tools.mutating`` from ``tools.allowlist``, so a
mutating tool that is served but not named is offered to every client while the
declaration says mutations are off.

Switching mutations on carries its own obligation. No surface does today, so a
test of the mutating path would assert against nothing and pass forever. What
survives that emptiness is a guard: a surface that permits mutations must name,
per required proof, the artifact that provides it, and the artifact must exist.
That converts an unverifiable promise into a reviewable declaration, and it
costs nothing until somebody flips the flag.

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
_PROOFS = (
    "confirmation",
    "authorization",
    "idempotency",
    "audit",
    "reversal",
)
_PRESENT_FILE = "README.md"


def missing_proofs(role: str, block: Mapping) -> list[str]:
    """Return what a mutation-permitting surface still owes, or an empty list.

    Args:
        role: the role the surface belongs to, for the message.
        block: its ``meta/mcp.yml`` mapping.

    A surface that keeps mutations off owes nothing here, which is every
    surface today, so the rule is exercised against a synthetic one rather
    than trusted to be right the first time somebody needs it.
    """
    tools = block.get("tools")
    if not isinstance(tools, Mapping) or not tools.get("mutating_tools_enabled"):
        return []

    proofs = block.get("mutating_proofs")
    if not isinstance(proofs, Mapping):
        return [
            (
                f"{role}: permits mutations without an mcp.mutating_proofs "
                f"block naming {list(_PROOFS)}"
            )
        ]

    missing = []
    for proof in _PROOFS:
        artifact = str(proofs.get(proof) or "").strip()
        if not artifact:
            missing.append(f"{role}: names no artifact for {proof!r}")
        elif not (PROJECT_ROOT / artifact).is_file():
            missing.append(
                f"{role}: names {artifact!r} for {proof!r}, which is not a file"
            )
    return missing


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

    def test_a_mutating_surface_names_an_artifact_per_required_proof(self) -> None:
        unproven = []
        for role, block in _surfaces():
            unproven.extend(missing_proofs(role, block))
        self.assertEqual(
            [],
            unproven,
            "mutating surface(s) without a named proof:\n"
            + "\n".join(f"  - {u}" for u in unproven),
        )

    def test_the_proof_rule_fires_on_a_surface_that_permits_mutations(self) -> None:
        bare = {"tools": {"mutating_tools_enabled": True}}
        self.assertEqual(
            1,
            len(missing_proofs("web-app-example", bare)),
            "no surface permits mutations today, so this rule would pass "
            "forever unless it is exercised against one that does",
        )

    def test_the_proof_rule_rejects_an_artifact_that_is_not_there(self) -> None:
        named = {
            "tools": {"mutating_tools_enabled": True},
            "mutating_proofs": dict.fromkeys(_PROOFS, "tests/nowhere.py"),
        }
        findings = missing_proofs("web-app-example", named)
        self.assertEqual(len(_PROOFS), len(findings))
        self.assertTrue(all("is not a file" in f for f in findings))

    def test_the_proof_rule_accepts_a_fully_proven_surface(self) -> None:
        proven = {
            "tools": {"mutating_tools_enabled": True},
            "mutating_proofs": dict.fromkeys(_PROOFS, _PRESENT_FILE),
        }
        self.assertEqual([], missing_proofs("web-app-example", proven))

    def test_a_read_only_surface_carries_no_mutating_proofs(self) -> None:
        premature = [
            f"{role}: declares mutating_proofs while mutations are off, so the "
            f"artifacts it names are never the thing under test"
            for role, block in _surfaces()
            if block.get("mutating_proofs")
            and not (block.get("tools") or {}).get("mutating_tools_enabled")
        ]
        self.assertEqual(
            [],
            premature,
            "read-only surface(s) carrying mutation proofs:\n"
            + "\n".join(f"  - {p}" for p in premature),
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
