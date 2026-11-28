from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from contextlib import redirect_stdout
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))
sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python/workspace"))

import members as m
import organization
import workspaces

from ._workspace_fake import SIGN_IN, WORKSPACES_CLIENT, FakeKeycloak

WS = "0f1e2d3c-4b5a-4968-8776-655443322110"
OTHER_WS = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
NEW_WS = "5d4c3b2a-1f0e-4d9c-8b7a-6f5e4d3c2b1a"
TWICE_WS = "6e5d4c3b-2a1f-4e0d-9c8b-7a6f5e4d3c2b"
ALICE = "11111111-1111-4111-8111-111111111111"
BOB = "22222222-2222-4222-8222-222222222222"
CAROL = "33333333-3333-4333-8333-333333333333"
STAFF = "44444444-4444-4444-8444-444444444444"
DAVE = "55555555-5555-4555-8555-555555555555"
KEY = "77777777-7777-4777-8777-777777777777"
KEY2 = "88888888-8888-4888-8888-888888888888"
STORE_CLIENT = "store-web"
SECRET = "f" * 64
INVITEE = "newcomer@example.com"
USERS = {
    ALICE: {
        "id": ALICE,
        "username": "alice",
        "email": "alice@example.com",
        "firstName": "Alice",
        "enabled": True,
    },
    BOB: {
        "id": BOB,
        "username": "bob",
        "email": "bob@example.com",
        "firstName": "Bob",
        "enabled": True,
    },
    CAROL: {
        "id": CAROL,
        "username": "carol",
        "email": "carol@example.com",
        "firstName": "Carol",
        "enabled": True,
    },
    STAFF: {
        "id": STAFF,
        "username": "staff",
        "email": "staff@example.com",
        "enabled": True,
        "groups": ["/roles/web-app-openbao/administrator"],
    },
    DAVE: {
        "id": DAVE,
        "username": "dave",
        "email": "dave@example.com",
        "firstName": "Dave",
        "enabled": True,
    },
}
WRITING = ("add", "invite", "uninvite", "role", "remove", "sync")


class Harness:
    def __init__(self) -> None:
        self.kc = FakeKeycloak(USERS)
        organization.apply(self.kc, WS, WORKSPACES_CLIENT)
        organization.apply(self.kc, OTHER_WS, WORKSPACES_CLIENT)
        self.kc.plant_org("twice-a", {organization.MARKER: [TWICE_WS]})
        self.kc.plant_org("twice-b", {organization.MARKER: [TWICE_WS]})
        self.org = next(
            org_id
            for org_id, org in self.kc.orgs.items()
            if org["attributes"].get(organization.MARKER) == [WS]
        )
        self.staged = {KEY: (INVITEE, "Admin"), KEY2: ("bob@example.com", "Viewer")}
        self.dir = tempfile.TemporaryDirectory()
        self.secret = Path(self.dir.name) / "secret"
        self.secret.write_text(SECRET, encoding="utf-8")
        self.roster = Path(self.dir.name) / "roster.json"
        self.writes_per_task: list[int] = []

    def env(self, action: str, workspace: str, **values: str) -> dict:
        """
        Args:
            action: MEMBERS_ACTION.
            workspace: WORKSPACE.
            **values: the action's further variables.

        Returns:
            The task environment members.sh hands over.
        """
        return {
            "KC_URL": "https://auth.example.com",
            "KC_REALM": "example.com",
            "KC_CLIENT_ID": "workspace-members",
            "KC_CLIENT_SECRET_FILE": str(self.secret),
            "KC_INVITE_CLIENT_ID": STORE_CLIENT,
            "KC_RBAC_GROUP_ROOT": "/roles",
            "KC_SIGN_IN_GROUP": SIGN_IN,
            "BAO_ADDR": "https://openbao.example.com",
            "BAO_TOKEN_FILE": str(self.secret),
            "MEMBERS_ROSTER_FILE": str(self.roster),
            "WORKSPACE": workspace,
            "MEMBERS_ACTION": action,
            **values,
        }

    def phase(self, phase: str, env: dict) -> tuple[int, list[str]]:
        """
        Args:
            phase: prepare, settle or list.
            env: the task environment.

        Returns:
            The exit status and stdout lines of members.py.
        """
        out = io.StringIO()
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(m, "service_account", lambda env: self.kc),
            mock.patch.object(m, "staged", lambda env, ws, key: self.staged[key]),
            redirect_stdout(out),
        ):
            status = m.main(["members.py", phase])
        return status, out.getvalue().splitlines()

    def task(
        self, action: str, workspace: str = WS, **values: str
    ) -> tuple[int, list[str]]:
        """
        Args:
            action: MEMBERS_ACTION.
            workspace: WORKSPACE.
            **values: the action's further variables.

        Returns:
            The exit status and output of one members task, as members.sh runs it.
        """
        env = self.env(action, workspace, **values)
        before = len(self.kc.writes)
        if action == "list":
            status, lines = self.phase("list", env)
        else:
            status, lines = self.phase("prepare", env)
            if status == 0:
                status, more = self.phase("settle", env)
                lines += more
        self.writes_per_task.append(len(self.kc.writes) - before)
        return status, lines

    def group(self, role: str) -> str:
        """
        Args:
            role: a role group.

        Returns:
            Its id in the organization of WS.
        """
        return next(
            g["id"] for g in self.kc.org_groups[self.org].values() if g["name"] == role
        )

    def member(self, user_id: str, *roles: str) -> None:
        """
        Args:
            user_id: a user made member of WS.
            *roles: the role groups the user joins.
        """
        self.kc.memberships[self.org][user_id] = "UNMANAGED"
        for role in roles:
            self.kc.group_members[self.group(role)].add(user_id)

    def roles(self, user_id: str) -> list[str]:
        """
        Args:
            user_id: a member of WS.

        Returns:
            The role groups the member holds.
        """
        return [
            r
            for r in organization.ROLES
            if user_id in self.kc.group_members[self.group(r)]
        ]

    def snapshot(self) -> dict:
        """
        Returns:
            Everything a members task may change.
        """
        return copy.deepcopy(
            {
                "orgs": self.kc.orgs,
                "memberships": self.kc.memberships,
                "group_members": self.kc.group_members,
                "invitations": self.kc.invitations,
            }
        )


def membership(lines: list[str]) -> dict:
    """
    Args:
        lines: output of a task.

    Returns:
        The parsed last line.
    """
    return json.loads(lines[-1])


def refused(status: int, lines: list[str], workspace: str, reason: str) -> bool:
    """
    Args:
        status: exit status.
        lines: output.
        workspace: the workspace id.
        reason: the expected reason.

    Returns:
        True when the task ended as error with exactly the refusal line.
    """
    return (
        status != 0
        and bool(lines)
        and lines[-1] == (f'{{"workspace":"{workspace}","refused":"{reason}"}}')
    )


def leaks(line: str) -> list[str]:
    """
    Args:
        line: a membership line.

    Returns:
        Every address, username or name of USERS and INVITEE it holds, and a
        missing ``enabled`` flag.
    """
    found = [
        value
        for user in USERS.values()
        for key in ("email", "username", "firstName")
        if (value := user.get(key)) and value in line
    ]
    if INVITEE in line:
        found.append(INVITEE)
    parsed = json.loads(line)
    found.extend(
        f"no enabled flag for {member['id']}"
        for member in parsed.get("members", [])
        if not isinstance(member.get("enabled"), bool)
    )
    return found


class TestMarker(unittest.TestCase):
    def setUp(self) -> None:
        self.h = Harness()

    def test_members_refuses_an_organization_without_one_marker(self) -> None:
        values = {
            "WORKSPACE_MEMBER": ALICE,
            "WORKSPACE_ROLE": "Admin",
            "INVITE_KEY": KEY,
        }
        for action in WRITING:
            with self.subTest(action=action, workspace="none"):
                before = self.h.snapshot()
                status, lines = self.h.task(action, NEW_WS, **values)
                self.assertTrue(refused(status, lines, NEW_WS, "absent"), lines)
                self.assertEqual(self.h.snapshot(), before)
            with self.subTest(action=action, workspace="two"):
                before = self.h.snapshot()
                status, lines = self.h.task(action, TWICE_WS, **values)
                self.assertEqual(status, 1)
                self.assertFalse([line for line in lines if "refused" in line])
                self.assertEqual(self.h.snapshot(), before)

    def test_list_reports_an_absent_organization(self) -> None:
        status, lines = self.h.task("list", NEW_WS)
        self.assertTrue(self.absent_listed(status, lines))
        self.assertEqual(self.h.writes_per_task[-1], 0)

    def test_the_absent_check_catches_a_list_that_fails(self) -> None:
        def strict(phase, env, log):
            raise workspaces.RefusalError("absent")

        with mock.patch.object(m, "run", strict):
            status, lines = self.h.task("list", NEW_WS)
        self.assertFalse(self.absent_listed(status, lines))

    @staticmethod
    def absent_listed(status: int, lines: list[str]) -> bool:
        return status == 0 and lines == [f'{{"workspace":"{NEW_WS}","absent":true}}']


class TestOwner(unittest.TestCase):
    def setUp(self) -> None:
        self.h = Harness()
        self.h.task("add", WORKSPACE_MEMBER=ALICE)

    def test_role_and_remove_keep_an_enabled_owner(self) -> None:
        before = self.h.snapshot()
        status, lines = self.h.task(
            "role", WORKSPACE_MEMBER=ALICE, WORKSPACE_ROLE="Admin"
        )
        self.assertTrue(refused(status, lines, WS, "last_owner"), lines)
        status, lines = self.h.task("remove", WORKSPACE_MEMBER=ALICE)
        self.assertTrue(refused(status, lines, WS, "last_owner"), lines)
        self.assertEqual(self.h.snapshot(), before)
        self.h.member(BOB, "Owner")
        self.h.kc.users[BOB]["enabled"] = False
        status, lines = self.h.task(
            "role", WORKSPACE_MEMBER=ALICE, WORKSPACE_ROLE="Admin"
        )
        self.assertTrue(refused(status, lines, WS, "last_owner"), lines)
        self.h.member(CAROL)
        status, _ = self.h.task("role", WORKSPACE_MEMBER=CAROL, WORKSPACE_ROLE="Owner")
        self.assertEqual(status, 0)
        status, lines = self.h.task(
            "role", WORKSPACE_MEMBER=ALICE, WORKSPACE_ROLE="Admin"
        )
        self.assertEqual(status, 0)
        self.assertEqual(self.h.roles(ALICE), ["Admin"])

    def test_the_owner_check_catches_a_disabled_owner_counted(self) -> None:
        def counts_disabled(self, user_id, roles):
            return sum(
                "Owner" in (roles if member_id == user_id else self.roles_of(member_id))
                for member_id in self.members
            )

        self.h.member(BOB, "Owner")
        self.h.kc.users[BOB]["enabled"] = False
        with mock.patch.object(workspaces.Workspace, "owners_after", counts_disabled):
            status, lines = self.h.task(
                "role", WORKSPACE_MEMBER=ALICE, WORKSPACE_ROLE="Admin"
            )
        self.assertFalse(refused(status, lines, WS, "last_owner"))

    def test_destroy_of_a_workspace_with_one_owner_succeeds(self) -> None:
        organization.destroy(self.h.kc, WS, WORKSPACES_CLIENT)
        self.assertNotIn(self.h.org, self.h.kc.orgs)

    def test_a_disabled_owner_shows_disabled(self) -> None:
        self.h.member(BOB, "Owner")
        self.h.kc.users[BOB]["enabled"] = False
        status, lines = self.h.task("list")
        self.assertEqual(status, 0)
        flags = {e["id"]: e["enabled"] for e in membership(lines)["members"]}
        self.assertEqual(flags, {ALICE: True, BOB: False})


class TestAdd(unittest.TestCase):
    def setUp(self) -> None:
        self.h = Harness()

    def test_add_makes_the_first_owner_and_a_rerun_changes_nothing(self) -> None:
        status, lines = self.h.task("add", WORKSPACE_MEMBER=ALICE)
        self.assertEqual(status, 0)
        self.assertEqual(self.h.roles(ALICE), ["Owner"])
        self.assertEqual(
            membership(lines)["members"],
            [{"id": ALICE, "groups": ["Owner"], "enabled": True}],
        )
        self.h.task("add", WORKSPACE_MEMBER=ALICE)
        self.assertEqual(self.h.writes_per_task[-1], 0)

    def test_add_refuses_a_second_member_or_a_pending_invitation(self) -> None:
        self.h.task("add", WORKSPACE_MEMBER=ALICE)
        before = self.h.snapshot()
        status, lines = self.h.task("add", WORKSPACE_MEMBER=BOB)
        self.assertTrue(refused(status, lines, WS, "not_first"), lines)
        self.assertEqual(self.h.snapshot(), before)
        fresh = Harness()
        fresh.task("invite", INVITE_KEY=KEY)
        status, lines = fresh.task("add", WORKSPACE_MEMBER=ALICE)
        self.assertTrue(refused(status, lines, WS, "not_first"), lines)


class TestInvitation(unittest.TestCase):
    def setUp(self) -> None:
        self.h = Harness()
        self.h.task("add", WORKSPACE_MEMBER=ALICE)

    def attributes(self) -> dict:
        return self.h.kc.orgs[self.h.org]["attributes"]

    def test_invite_reads_the_address_from_openbao(self) -> None:
        status, lines = self.h.task("invite", INVITE_KEY=KEY)
        self.assertEqual(status, 0)
        self.assertEqual(self.h.kc.mails, [(self.h.org, INVITEE, STORE_CLIENT)])
        self.assertEqual(self.attributes()["workspace.pending.Admin"], [KEY])
        self.assertEqual(self.attributes()["workspace.invite." + KEY], [INVITEE])
        self.assertEqual(self.attributes()[organization.MARKER], [WS])
        self.assertEqual(
            self.address_findings(self.h.env("invite", WS, INVITE_KEY=KEY), lines), []
        )
        self.assertEqual(membership(lines)["pending"], [{"key": KEY, "role": "Admin"}])

    def test_the_address_check_catches_an_address_in_the_task_input(self) -> None:
        env = self.h.env("invite", WS, INVITE_KEY=KEY, WORKSPACE_MEMBER_EMAIL=INVITEE)
        self.assertTrue(self.address_findings(env, []))

    @staticmethod
    def address_findings(env: dict, lines: list[str]) -> list[str]:
        found = [f"input {k}" for k, v in env.items() if INVITEE in v]
        found.extend(f"output {line}" for line in lines if INVITEE in line)
        return found

    def test_a_second_invite_with_the_same_key_sends_no_second_mail(self) -> None:
        self.h.task("invite", INVITE_KEY=KEY)
        status, _ = self.h.task("invite", INVITE_KEY=KEY)
        self.assertEqual(status, 0)
        self.assertEqual(len(self.h.kc.mails), 1)
        self.assertEqual(self.h.writes_per_task[-1], 0)

    def test_an_invitation_of_a_member_address_is_refused(self) -> None:
        self.h.member(BOB, "Viewer")
        before = self.h.snapshot()
        status, lines = self.h.task("invite", INVITE_KEY=KEY2)
        self.assertTrue(refused(status, lines, WS, "member_address"), lines)
        self.assertEqual(self.h.snapshot(), before)

    def test_uninvite_deletes_the_invitation_and_its_entry(self) -> None:
        self.h.task("invite", INVITE_KEY=KEY)
        status, lines = self.h.task("uninvite", INVITE_KEY=KEY)
        self.assertEqual(status, 0)
        self.assertEqual(self.h.kc.invitations[self.h.org], {})
        self.assertNotIn("workspace.pending.Admin", self.attributes())
        self.assertNotIn("workspace.invite." + KEY, self.attributes())
        self.assertEqual(membership(lines)["pending"], [])
        self.h.task("uninvite", INVITE_KEY=KEY)
        self.assertEqual(self.h.writes_per_task[-1], 0)

    def test_sync_places_an_accepted_invitee_into_the_invited_group(self) -> None:
        self.h.task("invite", INVITE_KEY=KEY)
        newcomer = self.h.kc.accept(self.h.org, INVITEE)
        status, lines = self.h.task("list")
        self.assertIn(
            {"id": newcomer, "groups": [], "enabled": True},
            membership(lines)["members"],
        )
        status, lines = self.h.task("sync")
        self.assertEqual(status, 0)
        self.assertEqual(self.h.roles(newcomer), ["Admin"])
        self.assertNotIn("workspace.invite." + KEY, self.attributes())
        self.assertEqual(membership(lines)["pending"], [])

    def test_sync_drops_an_entry_whose_invitation_keycloak_no_longer_holds(
        self,
    ) -> None:
        self.h.task("invite", INVITE_KEY=KEY)
        self.h.kc.invitations[self.h.org].clear()
        status, lines = self.h.task("sync")
        self.assertEqual(status, 0)
        self.assertEqual(membership(lines)["pending"], [])
        self.assertNotIn("workspace.pending.Admin", self.attributes())


class TestRole(unittest.TestCase):
    def setUp(self) -> None:
        self.h = Harness()
        self.h.task("add", WORKSPACE_MEMBER=ALICE)
        self.h.member(BOB, "Viewer", "Billing")

    def test_role_keeps_exactly_one_role_group(self) -> None:
        status, _ = self.h.task("role", WORKSPACE_MEMBER=BOB, WORKSPACE_ROLE="Operator")
        self.assertEqual(status, 0)
        self.assertEqual(self.h.roles(BOB), ["Operator"])
        self.h.task("role", WORKSPACE_MEMBER=BOB, WORKSPACE_ROLE="Operator")
        self.assertEqual(self.h.writes_per_task[-1], 0)

    def test_role_refuses_a_user_who_is_not_a_member(self) -> None:
        before = self.h.snapshot()
        status, lines = self.h.task(
            "role", WORKSPACE_MEMBER=CAROL, WORKSPACE_ROLE="Viewer"
        )
        self.assertTrue(refused(status, lines, WS, "not_member"), lines)
        self.assertEqual(self.h.snapshot(), before)


class TestRemove(unittest.TestCase):
    def setUp(self) -> None:
        self.h = Harness()
        self.h.task("add", WORKSPACE_MEMBER=ALICE)
        self.h.member(BOB, "Operator")

    def test_remove_takes_the_member_out_of_every_group_and_the_organization(
        self,
    ) -> None:
        status, lines = self.h.task("remove", WORKSPACE_MEMBER=BOB)
        self.assertEqual(status, 0)
        self.assertNotIn(BOB, self.h.kc.memberships[self.h.org])
        self.assertIn(BOB, self.h.kc.users)
        self.assertEqual([e["id"] for e in membership(lines)["members"]], [ALICE])

    def test_remove_of_a_former_member_succeeds_without_a_membership_call(self) -> None:
        self.h.task("remove", WORKSPACE_MEMBER=BOB)
        status, _ = self.h.task("remove", WORKSPACE_MEMBER=BOB)
        self.assertEqual(status, 0)
        self.assertEqual(self.h.writes_per_task[-1], 0)

    def test_remove_refuses_each_protected_member(self) -> None:
        self.h.member(STAFF, "Viewer")
        self.h.member(CAROL, "Viewer")
        self.h.kc.memberships[self.h.org][CAROL] = "MANAGED"
        for user_id, reason in ((CAROL, "managed"), (STAFF, "platform_role")):
            with self.subTest(reason=reason):
                before = self.h.snapshot()
                status, lines = self.h.task("remove", WORKSPACE_MEMBER=user_id)
                self.assertTrue(refused(status, lines, WS, reason), lines)
                self.assertEqual(self.h.snapshot(), before)

    def test_remove_takes_the_member_out_of_the_sign_in_group_first(self) -> None:
        self.h.kc.users[BOB]["groups"] = [SIGN_IN]
        status, lines = self.h.task("remove", WORKSPACE_MEMBER=BOB)
        self.assertEqual(status, 0, lines)
        self.assertEqual(self.h.kc.users[BOB]["groups"], [])
        left = f"change workspace={WS} action=remove user={BOB} group={SIGN_IN} change=left"
        ended = (
            f"change workspace={WS} action=remove user={BOB} change=left_organization"
        )
        self.assertLess(lines.index(left), lines.index(ended))
        self.assertNotIn(BOB, self.h.kc.memberships[self.h.org])

    def test_a_member_of_another_workspace_keeps_the_sign_in_group(self) -> None:
        self.h.kc.users[BOB]["groups"] = [SIGN_IN]
        other = next(
            org_id
            for org_id, org in self.h.kc.orgs.items()
            if org["attributes"].get(organization.MARKER) == [OTHER_WS]
        )
        self.h.kc.memberships[other][BOB] = "UNMANAGED"
        status, lines = self.h.task("remove", WORKSPACE_MEMBER=BOB)
        self.assertEqual(status, 0, lines)
        self.assertEqual(self.h.kc.users[BOB]["groups"], [SIGN_IN])
        self.assertNotIn(BOB, self.h.kc.memberships[self.h.org])

    def test_a_member_with_a_further_platform_role_is_still_refused(self) -> None:
        self.h.kc.users[BOB]["groups"] = [SIGN_IN, "/roles/web-app-semaphore/operator"]
        before = (self.h.snapshot(), copy.deepcopy(self.h.kc.users[BOB]))
        status, lines = self.h.task("remove", WORKSPACE_MEMBER=BOB)
        self.assertTrue(refused(status, lines, WS, "platform_role"), lines)
        self.assertEqual((self.h.snapshot(), self.h.kc.users[BOB]), before)

    def test_negative_control_a_guard_counting_the_sign_in_group_refuses(self) -> None:
        self.h.kc.users[BOB]["groups"] = [SIGN_IN]
        with mock.patch.object(self.h, "env", self.planted_env):
            status, lines = self.h.task("remove", WORKSPACE_MEMBER=BOB)
        self.assertTrue(refused(status, lines, WS, "platform_role"), lines)
        self.assertEqual(self.h.kc.users[BOB]["groups"], [SIGN_IN])
        self.assertIn(BOB, self.h.kc.memberships[self.h.org])

    def planted_env(self, action: str, workspace: str, **values: str) -> dict:
        return {
            **Harness.env(self.h, action, workspace, **values),
            "KC_SIGN_IN_GROUP": "",
        }


class TestOutput(unittest.TestCase):
    def setUp(self) -> None:
        self.h = Harness()
        self.h.task("add", WORKSPACE_MEMBER=ALICE)
        self.h.member(BOB, "Admin")
        self.h.task("invite", INVITE_KEY=KEY)

    def test_members_output_ends_with_the_membership(self) -> None:
        for action, values in (
            ("sync", {}),
            ("list", {}),
            ("role", {"WORKSPACE_MEMBER": BOB, "WORKSPACE_ROLE": "Admin"}),
        ):
            with self.subTest(action=action):
                status, lines = self.h.task(action, **values)
                self.assertEqual(status, 0)
                parsed = membership(lines)
                self.assertEqual(sorted(parsed), ["members", "pending", "workspace"])
                self.assertEqual(
                    parsed["members"],
                    [
                        {"id": ALICE, "groups": ["Owner"], "enabled": True},
                        {"id": BOB, "groups": ["Admin"], "enabled": True},
                    ],
                )
                self.assertEqual(parsed["pending"], [{"key": KEY, "role": "Admin"}])
                self.assertEqual(leaks(lines[-1]), [])

    def test_the_leak_check_catches_each_planted_field(self) -> None:
        _, lines = self.h.task("list")
        parsed = membership(lines)
        for planted in ("email", "username", "invitee", "enabled"):
            with self.subTest(planted=planted):
                broken = copy.deepcopy(parsed)
                if planted == "email":
                    broken["members"][0]["email"] = USERS[ALICE]["email"]
                if planted == "username":
                    broken["members"][0]["username"] = USERS[ALICE]["username"]
                if planted == "invitee":
                    broken["pending"][0]["address"] = INVITEE
                if planted == "enabled":
                    del broken["members"][0]["enabled"]
                self.assertTrue(leaks(json.dumps(broken)))

    def test_the_roster_carries_what_the_semaphore_mirror_needs(self) -> None:
        self.h.task("sync")
        roster = json.loads(
            self.h.roster.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        )
        bob = next(e for e in roster["members"] if e["id"] == BOB)
        self.assertEqual(
            (bob["username"], bob["email"], bob["groups"]),
            ("bob", "bob@example.com", ["Admin"]),
        )
        self.assertEqual(self.h.roster.stat().st_mode & 0o777, 0o600)

    def test_members_prints_each_change(self) -> None:
        status, lines = self.h.task(
            "role", WORKSPACE_MEMBER=BOB, WORKSPACE_ROLE="Viewer"
        )
        self.assertEqual(status, 0)
        self.assertIn(
            f"change workspace={WS} action=role user={BOB} group=Viewer change=joined",
            lines,
        )
        self.assertIn(
            f"change workspace={WS} action=role user={BOB} group=Admin change=left",
            lines,
        )
        self.assertEqual(self.secret_findings(lines), [])

    def test_the_secret_check_catches_a_printed_secret(self) -> None:
        self.assertTrue(self.secret_findings(["change", f"failed token {SECRET}"]))

    @staticmethod
    def secret_findings(lines: list[str]) -> list[str]:
        return [line for line in lines if SECRET in line]


class TestRefusals(unittest.TestCase):
    def setUp(self) -> None:
        self.h = Harness()
        self.h.task("add", WORKSPACE_MEMBER=ALICE)
        self.h.member(BOB, "Viewer")
        self.h.member(STAFF, "Viewer")
        self.h.member(CAROL, "Viewer")
        self.h.kc.memberships[self.h.org][CAROL] = "MANAGED"

    def cases(self) -> list[tuple[str, dict, str, str]]:
        return [
            (
                "role",
                {"WORKSPACE_MEMBER": ALICE, "WORKSPACE_ROLE": "Viewer"},
                WS,
                "last_owner",
            ),
            ("add", {"WORKSPACE_MEMBER": DAVE}, WS, "not_first"),
            ("invite", {"INVITE_KEY": KEY2}, WS, "member_address"),
            (
                "role",
                {"WORKSPACE_MEMBER": DAVE, "WORKSPACE_ROLE": "Viewer"},
                WS,
                "not_member",
            ),
            ("remove", {"WORKSPACE_MEMBER": CAROL}, WS, "managed"),
            ("remove", {"WORKSPACE_MEMBER": STAFF}, WS, "platform_role"),
            ("sync", {}, NEW_WS, "absent"),
        ]

    def test_each_refusal_ends_with_its_reason(self) -> None:
        for action, values, workspace, reason in self.cases():
            with self.subTest(reason=reason):
                status, lines = self.h.task(action, workspace, **values)
                self.assertEqual(status, m.REFUSED)
                self.assertTrue(refused(status, lines, workspace, reason), lines)

    def test_a_failed_keycloak_call_ends_without_a_refusal(self) -> None:
        self.h.kc.fail_at = len(self.h.kc.writes)
        status, lines = self.h.task(
            "role", WORKSPACE_MEMBER=BOB, WORKSPACE_ROLE="Admin"
        )
        self.assertEqual(status, m.FAILED)
        self.assertFalse([line for line in lines if "refused" in line])

    def test_the_refusal_check_catches_a_refusal_that_ends_with_success(self) -> None:
        self.assertFalse(
            refused(
                0, [f'{{"workspace":"{WS}","refused":"last_owner"}}'], WS, "last_owner"
            )
        )


class TestRetry(unittest.TestCase):
    def scenario(self, action: str) -> tuple[Harness, dict]:
        h = Harness()
        h.task("add", WORKSPACE_MEMBER=ALICE)
        h.member(BOB, "Viewer")
        h.kc.users[BOB]["groups"] = [SIGN_IN]
        if action in ("uninvite", "sync"):
            h.task("invite", INVITE_KEY=KEY)
        if action == "sync":
            h.kc.accept(h.org, INVITEE)
        values = {
            "add": {"WORKSPACE_MEMBER": ALICE},
            "invite": {"INVITE_KEY": KEY},
            "uninvite": {"INVITE_KEY": KEY},
            "role": {"WORKSPACE_MEMBER": BOB, "WORKSPACE_ROLE": "Operator"},
            "remove": {"WORKSPACE_MEMBER": BOB},
            "sync": {},
        }[action]
        return h, values

    def test_each_members_action_finishes_after_a_failure_at_each_step(self) -> None:
        for action in WRITING:
            clean, values = self.scenario(action)
            start = len(clean.kc.writes)
            clean.task(action, **values)
            steps = len(clean.kc.writes) - start
            if action != "add":
                self.assertGreater(steps, 0, action)
            for step in range(steps):
                with self.subTest(action=action, step=step):
                    h, _ = self.scenario(action)
                    h.kc.fail_at = len(h.kc.writes) + step
                    status, _ = h.task(action, **values)
                    self.assertEqual(status, m.FAILED)
                    status, _ = h.task(action, **values)
                    self.assertEqual(status, 0)
                    h.task(action, **values)
                    self.assertEqual(h.writes_per_task[-1], 0)
                    self.assertEqual(self.outcome(h), self.outcome(clean))

    @staticmethod
    def outcome(h: Harness) -> tuple:
        return (
            {u: h.roles(u) for u in sorted(h.kc.memberships[h.org])},
            h.kc.orgs[h.org]["attributes"],
            sorted(i["email"] for i in h.kc.invitations[h.org].values()),
            h.kc.users[BOB]["groups"],
        )


class TestList(unittest.TestCase):
    def setUp(self) -> None:
        self.h = Harness()
        self.h.task("add", WORKSPACE_MEMBER=ALICE)
        self.h.member(BOB, "Admin")
        self.h.task("invite", INVITE_KEY=KEY)

    def test_list_changes_nothing(self) -> None:
        self.h.kc.accept(self.h.org, INVITEE)
        before = self.h.snapshot()
        status, first = self.h.task("list")
        status_again, second = self.h.task("list")
        self.assertEqual((status, status_again), (0, 0))
        self.assertEqual(self.h.writes_per_task[-2:], [0, 0])
        self.assertEqual(first, second)
        self.assertEqual(self.h.snapshot(), before)

    def test_list_prints_the_line_of_a_sync_of_an_unchanged_organization(self) -> None:
        _, listed = self.h.task("list")
        _, synced = self.h.task("sync")
        self.assertEqual(listed[-1], synced[-1])
        self.assertEqual(self.h.writes_per_task[-1], 0)

    def test_the_list_check_catches_a_list_that_ends_with_sync(self) -> None:
        self.h.kc.accept(self.h.org, INVITEE)
        original = m.run

        def with_sync(phase, env, log):
            if phase == "list":
                return original("settle", {**env, "MEMBERS_ACTION": "sync"}, log)
            return original(phase, env, log)

        with mock.patch.object(m, "run", with_sync):
            self.h.task("list")
        self.assertGreater(self.h.writes_per_task[-1], 0)

    def test_list_shows_one_workspace_only(self) -> None:
        other = next(
            org_id
            for org_id, org in self.h.kc.orgs.items()
            if org["attributes"].get(organization.MARKER) == [OTHER_WS]
        )
        self.h.kc.memberships[other][CAROL] = "UNMANAGED"
        _, lines = self.h.task("list")
        self.assertNotIn(CAROL, lines[-1])


if __name__ == "__main__":
    unittest.main()
