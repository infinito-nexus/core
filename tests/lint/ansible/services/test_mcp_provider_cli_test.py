"""Lint: an enabled MCP provider ships a CLI test for its endpoint.

``auth_subject``, ``credential.owner`` and ``tools.allowlist`` are declarations.
Nothing stops a role from declaring one principal and provisioning another, or
from advertising tools the server never exposes; a client would then discover an
endpoint whose credential belongs to nobody, or whose allowlist is fiction.

Every provider closes that gap the same way: ``files/test/test.sh`` drives the
shared contract harness, which speaks the declared transport against the live
endpoint with the header a client would send, compares ``tools/list`` against
the allowlist and calls the declared read probe. A provider without that test
has a documentation-only identity.

Disabled providers are exempt: they serve nothing, so there is nothing to prove
until an operator turns them on.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-provider-cli-test`` in the head of the role's ``meta/mcp.yml``.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.applications import get_application_defaults
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

_RULE = "mcp-provider-cli-test"
_SERVER_DIRECTIONS = frozenset({"server", "both"})
_SCRIPT = "files/test/test.sh"
_ENV_TEMPLATE = "templates/test.env.j2"
_HARNESS = "shared/mcp/run.sh"


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


def _missing_asset(role_dir: Path) -> str | None:
    """Return why the role has no usable MCP CLI test, or None when it has one."""
    script = role_dir / _SCRIPT
    if not script.is_file():
        return f"missing {_SCRIPT}"
    if not (role_dir / _ENV_TEMPLATE).is_file():
        return f"missing {_ENV_TEMPLATE}, so no round ever discovers the test"
    if _HARNESS not in read_text(str(script)):
        return f"{_SCRIPT} never drives {_HARNESS}"
    return None


class TestMcpProviderCliTest(unittest.TestCase):
    def test_every_enabled_provider_tests_its_endpoint(self) -> None:
        offenders = [
            f"{role.name}: serves MCP but {why}, so its declared credential "
            f"owner and tool allowlist are never proven against the endpoint"
            for role in _enabled_providers()
            if (why := _missing_asset(role)) is not None
        ]
        self.assertEqual(
            [],
            offenders,
            f"MCP provider(s) with an unproven endpoint ({len(offenders)}):\n"
            + "\n".join(f"  - {o}" for o in offenders),
        )

    def test_the_scan_finds_enabled_providers(self) -> None:
        self.assertTrue(
            _enabled_providers(),
            "no MCP block declares an enabled server, so the rule would pass "
            "vacuously; check that the scan still reads the right topic",
        )


if __name__ == "__main__":
    unittest.main()
