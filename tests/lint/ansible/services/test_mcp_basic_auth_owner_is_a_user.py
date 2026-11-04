"""Lint: a basic-auth MCP provider's credential owner is a declared user.

``credential.owner`` is the users-dict key the token store writes under. For
every bearer scheme that key never leaves the deployment, but ``basic_auth``
puts a name on the wire: ``mcp_authorization`` encodes ``login:token``, where
the login is ``users[owner].username``.

``resolve_credential`` falls back to the owner key when the users dict declares
no such principal, which is right for a bearer provider and silently wrong for
a basic-auth one: the endpoint is handed a user name that was never created,
answers 401, and the failure reads like a broken secret rather than a missing
account. web-app-wordpress reached that same 401 by the other route, a declared
principal whose ``username`` the renderer ignored; this rule closes the route
that is left, where there is no principal to read a username from at all.

The scan reads the auth set the filter itself branches on, so the rule and the
renderer cannot drift onto different spellings of basic auth.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-basic-auth-owner-is-a-user`` in the head of the role's
  ``meta/mcp.yml``.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path

from plugins.filter.mcp.authorization import BASIC_AUTHS
from tests.utils.role_users import declared_universe
from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.mcp import MCP_AUTHS, MCP_SERVER_DIRECTIONS
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

_RULE = "mcp-basic-auth-owner-is-a-user"


def _providers() -> list[tuple[str, Mapping]]:
    """Return ``(role_id, mcp_block)`` for every role declaring an MCP server."""
    roles_root = Path(PROJECT_ROOT, "roles")
    found: list[tuple[str, Mapping]] = []
    for mcp_path in sorted(roles_root.glob(f"*/{ROLE_FILE_META_MCP}")):
        mcp = load_yaml_any(str(mcp_path), default_if_missing={})
        if not isinstance(mcp, Mapping):
            continue
        if str(mcp.get("direction") or "").strip().lower() not in MCP_SERVER_DIRECTIONS:
            continue
        if is_suppressed_in_head(read_text(str(mcp_path)).splitlines(), _RULE):
            continue
        found.append((mcp_path.parent.parent.name, mcp))
    return found


def _undeclared_owners() -> list[str]:
    """Return one finding per basic-auth provider whose owner is not a user."""
    universe = declared_universe(Path(PROJECT_ROOT, "roles"))
    findings: list[str] = []
    for role_id, mcp in _providers():
        if str(mcp.get("auth") or "").strip().lower() not in BASIC_AUTHS:
            continue
        credential = mcp.get("credential")
        owner = str(
            (credential.get("owner") if isinstance(credential, Mapping) else "") or ""
        ).strip()
        if owner in universe:
            continue
        findings.append(
            f"{role_id}: credential.owner {owner!r} is declared by no role's "
            f"meta/users.yml, so the basic-auth login falls back to the owner "
            f"key instead of resolving users[{owner!r}].username; the endpoint "
            f"would authenticate an account that was never created and answer "
            f"401 on every MCP call"
        )
    return findings


class TestMcpBasicAuthOwnerIsAUser(unittest.TestCase):
    def test_every_basic_auth_owner_resolves_to_a_declared_principal(self) -> None:
        findings = _undeclared_owners()
        self.assertEqual(
            [],
            findings,
            f"basic-auth MCP provider(s) whose owner is not a user "
            f"({len(findings)}):\n" + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_reads_the_auth_it_filters_on(self) -> None:
        """Guard the extraction, not the population.

        A deployment with no basic-auth provider has nothing to check and may
        pass with an empty list. What must never happen is the rule matching
        nothing because it reads the wrong key or a spelling the renderer does
        not treat as basic auth, which looks identical from the outside.
        """
        self.assertTrue(
            BASIC_AUTHS <= MCP_AUTHS,
            f"the renderer treats {sorted(BASIC_AUTHS)} as basic auth but the "
            f"schema admits {sorted(MCP_AUTHS)}, so this rule would scan for a "
            f"value no meta/mcp.yml can carry",
        )
        observed = {
            str(mcp.get("auth") or "").strip().lower() for _, mcp in _providers()
        }
        self.assertTrue(
            observed,
            "no role declares an MCP server, so the scan reads nothing at all; "
            "check that it still finds the right topic",
        )
        self.assertEqual(
            set(),
            observed - MCP_AUTHS,
            f"the scan read {sorted(observed - MCP_AUTHS)} where an auth was "
            f"expected, so the key it filters on is not the one meta/mcp.yml "
            f"declares and every provider would slip past this rule",
        )


if __name__ == "__main__":
    unittest.main()
