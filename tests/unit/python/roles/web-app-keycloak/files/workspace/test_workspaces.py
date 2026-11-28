from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))
sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python/workspace"))

import organization
import workspaces as m

from ._workspace_fake import (
    MANAGED,
    OTHER_WS,
    OWNER,
    ROOT,
    STAFF,
    USERS,
    WORKSPACES_CLIENT,
    WS,
    FakeKeycloak,
)


def owners_ignoring_enabled(ws: m.Workspace, user_id: str, roles: list[str]) -> int:
    """
    Args:
        ws: a loaded workspace.
        user_id: the member a change concerns.
        roles: the role groups that member holds after the change.

    Returns:
        How many members hold Owner after the change, disabled ones counted.
    """
    return sum(
        "Owner" in (roles if member_id == user_id else ws.roles_of(member_id))
        for member_id in ws.members
    )


class TestWorkspace(unittest.TestCase):
    def setUp(self) -> None:
        users = copy.deepcopy(USERS)
        users[MANAGED]["enabled"] = False
        self.kc = FakeKeycloak(users)
        organization.apply(self.kc, WS, WORKSPACES_CLIENT)
        (self.org_id,) = self.kc.orgs
        groups = {g["name"]: g["id"] for g in self.kc.org_groups[self.org_id].values()}
        for user_id in (OWNER, MANAGED):
            self.kc.memberships[self.org_id][user_id] = "UNMANAGED"
            self.kc.group_members[groups["Owner"]].add(user_id)

    def test_load_reads_the_marked_organization_only(self) -> None:
        self.assertIsNone(m.Workspace.load(self.kc, OTHER_WS, "add"))
        ws = m.Workspace.load(self.kc, WS, "add")
        self.assertEqual(ws.base, f"organizations/{self.org_id}")
        self.assertEqual(sorted(ws.members), sorted([OWNER, MANAGED]))
        self.assertEqual(ws.roles_of(OWNER), ["Owner"])

    def test_a_disabled_owner_does_not_count(self) -> None:
        ws = m.Workspace.load(self.kc, WS, "role")
        self.assertEqual(ws.owners_after(OWNER, ["Owner"]), 1)
        self.assertEqual(ws.owners_after(OWNER, ["Admin"]), 0)

    def test_negative_control_a_count_of_disabled_owners_keeps_one(self) -> None:
        ws = m.Workspace.load(self.kc, WS, "role")
        self.assertEqual(owners_ignoring_enabled(ws, OWNER, ["Admin"]), 1)

    def test_rbac_member_holds_only_below_the_root(self) -> None:
        self.assertTrue(m.rbac_member(self.kc, STAFF, ROOT))
        self.assertFalse(m.rbac_member(self.kc, OWNER, ROOT))
        self.assertFalse(m.rbac_member(self.kc, STAFF, "/role"))

    def test_keycloak_id_refuses_a_malformed_value(self) -> None:
        self.assertEqual(m.keycloak_id(OWNER, "WORKSPACE_MEMBER"), OWNER)
        for value in ("", "alice", WS.upper(), OWNER + "0"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "WORKSPACE_MEMBER"),
            ):
                m.keycloak_id(value, "WORKSPACE_MEMBER")

    def test_write_private_leaves_a_file_only_its_owner_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roster.json"
            m.write_private(str(path), {"workspace": WS})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                path.read_text(encoding="utf-8"),  # nocheck: cache-read tempdir
                f'{{"workspace": "{WS}"}}',
            )


if __name__ == "__main__":
    unittest.main()
