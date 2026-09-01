"""Lint: an enabled MCP surface is covered by a Playwright spec of its own.

The deploy-time provider probe proves the endpoint answers *its* credential. It
says nothing about what the endpoint answers a stranger, because it never asks
without one. That question belongs to a browser-side spec, and a role that
turns its MCP surface on without one ships an endpoint nobody ever asked the
hostile question of.

Two relations per role whose ``meta/mcp.yml`` is enabled:

* it ships at least one file under ``files/playwright/`` whose name carries
  ``mcp``, so the surface has a spec rather than being covered incidentally by
  a persona test;
* a role serving MCP additionally asserts the unauthenticated case somewhere in
  those files. The anchor is vocabulary — ``unauthenticated``, ``bearerless``,
  ``without a bearer``, ``refus…`` or ``reject…`` — so name the assertion in
  those words rather than leaving a reader to infer it.

Disabled surfaces are exempt: nothing is served until an operator turns them on.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-playwright-coverage`` in the head of the role's
  ``meta/mcp.yml``.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.applications import get_application_defaults
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

_RULE = "mcp-playwright-coverage"
_SERVER_DIRECTIONS = frozenset({"server", "both"})
_CLIENT_DIRECTIONS = frozenset({"client", "both"})
_UNAUTHENTICATED = re.compile(
    r"unauthenticated|bearerless|without a bearer|refus|reject", re.IGNORECASE
)
_CLIENT_SURFACE = re.compile(
    r"unauthenticated|refus|reject|server list|servers\b", re.IGNORECASE
)


def _enabled_mcp_roles() -> dict[str, str]:
    """Return ``{role: direction}`` for every role serving or consuming MCP."""
    roles_root = Path(PROJECT_ROOT, "roles")
    defaults = get_application_defaults(roles_dir=roles_root)
    roles: dict[str, str] = {}
    for mcp_path in sorted(roles_root.glob(f"*/{ROLE_FILE_META_MCP}")):
        mcp = load_yaml_any(str(mcp_path), default_if_missing={})
        if not isinstance(mcp, Mapping):
            continue
        role = mcp_path.parent.parent.name
        block = (defaults.get(role) or {}).get("mcp")
        if not (block.get("enabled") if isinstance(block, Mapping) else None):
            continue
        if is_suppressed_in_head(read_text(str(mcp_path)).splitlines(), _RULE):
            continue
        roles[role] = str(mcp.get("direction") or "").strip().lower()
    return roles


def _mcp_specs(role: str) -> list[Path]:
    directory = PROJECT_ROOT / "roles" / role / "files" / "playwright"
    return sorted(p for p in directory.glob("*.js") if "mcp" in p.name)


class TestMcpPlaywrightCoverage(unittest.TestCase):
    def test_every_enabled_surface_has_a_spec(self) -> None:
        missing = [
            f"{role}: its MCP surface is enabled but files/playwright/ holds no "
            f"mcp spec, so nothing exercises it from outside the deploy"
            for role in sorted(_enabled_mcp_roles())
            if not _mcp_specs(role)
        ]
        self.assertEqual(
            [],
            missing,
            f"enabled MCP surface(s) without a spec ({len(missing)}):\n"
            + "\n".join(f"  - {m}" for m in missing),
        )

    def test_every_served_surface_asserts_the_unauthenticated_case(self) -> None:
        silent = []
        for role, direction in sorted(_enabled_mcp_roles().items()):
            if direction not in _SERVER_DIRECTIONS:
                continue
            specs = _mcp_specs(role)
            if specs and not any(
                _UNAUTHENTICATED.search(read_text(str(spec))) for spec in specs
            ):
                silent.append(
                    f"{role}: serves MCP but no spec names the unauthenticated "
                    f"case, so the endpoint is only ever asked with a valid "
                    f"credential"
                )
        self.assertEqual(
            [],
            silent,
            f"served MCP surface(s) never probed anonymously ({len(silent)}):\n"
            + "\n".join(f"  - {s}" for s in silent),
        )

    def test_every_served_surface_asserts_the_disabled_case(self) -> None:
        silent = []
        for role, direction in sorted(_enabled_mcp_roles().items()):
            if direction not in _SERVER_DIRECTIONS:
                continue
            specs = _mcp_specs(role)
            if specs and not any(
                "registerMcpDisabledState" in read_text(str(spec)) for spec in specs
            ):
                silent.append(
                    f"{role}: every MCP spec here skips itself when the surface "
                    f"is switched off, so one that kept serving afterwards looks "
                    f"exactly like one that was never deployed"
                )
        self.assertEqual(
            [],
            silent,
            f"served MCP surface(s) never probed while disabled ({len(silent)}):\n"
            + "\n".join(f"  - {s}" for s in silent),
        )

    def test_every_consumed_surface_asserts_what_the_client_exposes(self) -> None:
        silent = []
        for role, direction in sorted(_enabled_mcp_roles().items()):
            if direction not in _CLIENT_DIRECTIONS:
                continue
            specs = _mcp_specs(role)
            if specs and not any(
                _CLIENT_SURFACE.search(read_text(str(spec))) for spec in specs
            ):
                silent.append(
                    f"{role}: consumes MCP but no spec asserts either the "
                    f"configured server list or that its own API refuses an "
                    f"unauthenticated caller, so the credential it holds is "
                    f"never shown to be out of reach"
                )
        self.assertEqual(
            [],
            silent,
            f"MCP client(s) with an unexercised surface ({len(silent)}):\n"
            + "\n".join(f"  - {s}" for s in silent),
        )

    def test_the_scan_finds_enabled_surfaces(self) -> None:
        roles = _enabled_mcp_roles()
        self.assertTrue(
            roles,
            "no role enables an MCP surface, so both rules would pass "
            "vacuously; check that the scan still reads the right topic",
        )
        self.assertTrue(
            any(d in _SERVER_DIRECTIONS for d in roles.values()),
            "no enabled role serves MCP, so the anonymous-probe rule would "
            "pass vacuously",
        )
        self.assertTrue(
            any(d in _CLIENT_DIRECTIONS for d in roles.values()),
            "no enabled role consumes MCP, so the client-surface rule would "
            "pass vacuously",
        )


if __name__ == "__main__":
    unittest.main()
