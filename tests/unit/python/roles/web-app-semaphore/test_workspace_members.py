from __future__ import annotations

import unittest
from unittest import mock

from .files._semaphore_fake import WORKSPACE_ID, FakeSemaphore
from .files.test_semaphore_members import MEMBERS, load_members, roster

MEMBER = "f1111111-0000-4000-8000-000000000006"
ROLE_MAP = {
    "Owner": "task_runner",
    "Admin": "task_runner",
    "Operator": "task_runner",
    "Viewer": "guest",
    "Billing": None,
}
WIDEST = (["Viewer", "Operator"], "task_runner")


def mapped_role(members, groups):
    """Args:
        members: the module ``semaphore_members.py``.
        groups: the role groups of one member.

    Returns:
        The Semaphore role the sync gives that member, None for none.
    """
    desired = members.desired_roles(roster((MEMBER, "member", groups)), False)
    return desired[MEMBER][1] if MEMBER in desired else None


def role_map_findings(members):
    """Args:
        members: the module ``semaphore_members.py``.

    Returns:
        One finding per role group that maps onto another role than
        ``ROLE_MAP`` and one when several groups do not give the widest.
    """
    findings = [
        f"{group} maps onto {mapped_role(members, [group])}, expected {role}"
        for group, role in ROLE_MAP.items()
        if mapped_role(members, [group]) != role
    ]
    groups, widest = WIDEST
    if mapped_role(members, groups) != widest:
        findings.append(
            f"{groups} map onto {mapped_role(members, groups)}, expected {widest}"
        )
    return findings


class TestWorkspaceMembers(unittest.TestCase):
    def setUp(self):
        self.members = load_members()

    def test_the_role_map_is_fixed(self):
        self.assertEqual(role_map_findings(self.members), [])

    def test_negative_control_owner_onto_owner(self):
        roles = {**self.members.ROLES, "Owner": "owner"}
        rank = {**self.members.RANK, "owner": 3}
        with (
            mock.patch.object(self.members, "ROLES", roles),
            mock.patch.object(self.members, "RANK", rank),
        ):
            self.assertEqual(
                role_map_findings(self.members),
                ["Owner maps onto owner, expected task_runner"],
            )

    def test_negative_control_billing_onto_guest(self):
        roles = {**self.members.ROLES, "Billing": "guest"}
        with mock.patch.object(self.members, "ROLES", roles):
            self.assertEqual(
                role_map_findings(self.members),
                ["Billing maps onto guest, expected None"],
            )

    def test_negative_control_the_narrowest_role_wins(self):
        with mock.patch.object(self.members, "RANK", {"task_runner": 1, "guest": 2}):
            self.assertEqual(
                role_map_findings(self.members),
                ["['Viewer', 'Operator'] map onto guest, expected task_runner"],
            )

    def planted_sync(self, role):
        api = FakeSemaphore(self.members.SyncError)
        project_id = api.add_project(f"ws-{WORKSPACE_ID}")["id"]
        api.users.append({"id": 2, "username": "store", "admin": False})
        api.users.append({"id": 9, "username": "mallory", "admin": False})
        api.members[project_id][2] = "manager"
        api.members[project_id][9] = role
        before = len(api.writes)
        error = None
        try:
            self.members.sync(
                api,
                WORKSPACE_ID,
                project_id,
                roster(*MEMBERS),
                False,
                {"store"},
                lambda line: None,
            )
        except self.members.SyncError as raised:
            error = str(raised)
        return error, api.writes[before:], project_id

    def test_sync_refuses_a_member_with_edit_rights(self):
        for role in ("manager", "owner"):
            with self.subTest(role):
                error, writes, _ = self.planted_sync(role)
                self.assertIn("account=9", error or "")
                self.assertEqual(writes, [])

    def test_negative_control_a_member_without_edit_rights_is_realigned(self):
        error, writes, project_id = self.planted_sync("task_runner")
        self.assertIsNone(error)
        self.assertIn(("DELETE", f"/project/{project_id}/users/9"), writes)


if __name__ == "__main__":
    unittest.main()
