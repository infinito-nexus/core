from __future__ import annotations

import copy
import io
import sys
import unittest
import urllib.parse
from contextlib import redirect_stdout
from unittest import mock

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))
sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python/workspace"))

import organization as m

from ._workspace_fake import (
    OTHER_WS,
    USERS,
    WORKSPACES_CLIENT,
    WORKSPACES_UUID,
    WS,
    FakeKeycloak,
    state,
)


def acted_on_unmarked(fake: FakeKeycloak, org_id: str) -> bool:
    """
    Args:
        fake: the fake Keycloak.
        org_id: an organization without the workspace marker.

    Returns:
        True when any write touched that organization.
    """
    return any(org_id in path for _, path, _ in fake.writes)


def find_by_alias(kc, workspace):
    query = urllib.parse.urlencode({"q": f"alias:{m.alias(workspace)}", "max": 2})
    found, _ = kc.call("GET", f"organizations?{query}")
    return found[0] if found else None


def strict_delete(kc, path):
    kc.call("DELETE", path)
    return "deleted"


class FakeWithAliasSearch(FakeKeycloak):
    def _search_orgs(self, params):
        key, _, value = params["q"].partition(":")
        if key == "alias":
            return [copy.deepcopy(o) for o in self.orgs.values() if o["alias"] == value]
        return super()._search_orgs(params)


class TestApply(unittest.TestCase):
    def setUp(self) -> None:
        self.kc = FakeKeycloak(USERS)

    def test_apply_creates_one_marked_organization_with_groups_roles_and_mappings(
        self,
    ) -> None:
        m.apply(self.kc, WS, WORKSPACES_CLIENT)
        (org,) = self.kc.orgs.values()
        self.assertEqual((org["name"], org["alias"]), (f"ws-{WS}", f"ws-{WS}"))
        self.assertEqual(org["attributes"], {m.MARKER: [WS]})
        groups = {g["name"]: g for g in self.kc.org_groups[org["id"]].values()}
        self.assertEqual(sorted(groups), sorted(m.ROLES))
        self.assertEqual(
            sorted(self.kc.client_roles), sorted(f"{WS}:{r}" for r in m.ROLES)
        )
        for role in m.ROLES:
            self.assertEqual(
                groups[role]["clientRoles"], {WORKSPACES_CLIENT: [f"{WS}:{role}"]}
            )

    def test_apply_finds_its_organization_by_the_marker(self) -> None:
        m.apply(self.kc, WS, WORKSPACES_CLIENT)
        before = state(self.kc)
        self.kc.writes.clear()
        lines = m.apply(self.kc, WS, WORKSPACES_CLIENT)
        self.assertEqual(len(self.kc.orgs), 1)
        self.assertEqual(self.kc.writes, [])
        self.assertEqual(state(self.kc), before)
        self.assertTrue(all(line.startswith("unchanged ") for line in lines))

    def test_an_apply_on_an_unmarked_alias_fails_and_changes_nothing(self) -> None:
        planted = self.kc.plant_org(f"ws-{WS}", {})
        before = state(self.kc)
        with self.assertRaises(m.KeycloakHTTPError) as raised:
            m.apply(self.kc, WS, WORKSPACES_CLIENT)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(state(self.kc), before)
        self.assertFalse(acted_on_unmarked(self.kc, planted))

    def test_the_marker_check_catches_a_lookup_by_alias(self) -> None:
        kc = FakeWithAliasSearch(USERS)
        planted = kc.plant_org(f"ws-{WS}", {})
        with mock.patch.object(m, "find", find_by_alias):
            m.apply(kc, WS, WORKSPACES_CLIENT)
        self.assertTrue(acted_on_unmarked(kc, planted))

    def test_apply_never_writes_an_existing_organization(self) -> None:
        m.apply(self.kc, WS, WORKSPACES_CLIENT)
        (org_id,) = self.kc.orgs
        self.kc.orgs[org_id]["attributes"].update(
            {
                "workspace.pending.Admin": ["k1"],
                "workspace.invite.k1": ["a@example.com"],
            }
        )
        self.kc.writes.clear()
        m.apply(self.kc, WS, WORKSPACES_CLIENT)
        self.assertFalse(
            [w for w in self.kc.writes if w[1] == f"organizations/{org_id}"]
        )
        self.assertEqual(self.kc.orgs[org_id]["attributes"][m.MARKER], [WS])
        self.assertEqual(
            self.kc.orgs[org_id]["attributes"]["workspace.invite.k1"], ["a@example.com"]
        )

    def test_two_marked_organizations_stop_the_task(self) -> None:
        self.kc.plant_org("a", {m.MARKER: [WS]})
        self.kc.plant_org("b", {m.MARKER: [WS]})
        before = state(self.kc)
        for run in (m.apply, m.destroy):
            with self.subTest(action=run.__name__), self.assertRaises(m.AmbiguousError):
                run(self.kc, WS, WORKSPACES_CLIENT)
        self.assertEqual(state(self.kc), before)

    def test_a_malformed_workspace_id_is_refused(self) -> None:
        for value in ("", f"ws-{WS}", WS.upper(), WS + "0", "../x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.validate(value)


def owner_id(kc: FakeKeycloak, workspace: str) -> str:
    """
    Args:
        kc: the fake after an apply.
        workspace: the workspace id.

    Returns:
        The id of the group ``Owner`` the apply created in the marked organization.
    """
    (org_id,) = [
        org_id
        for org_id, org in kc.orgs.items()
        if workspace in org["attributes"].get(m.MARKER, [])
    ]
    (group_id,) = [
        g["id"] for g in kc.org_groups[org_id].values() if g["name"] == m.OWNER
    ]
    return group_id


def main_output(kc: FakeKeycloak, action: str) -> tuple[int, list[str]]:
    """
    Args:
        kc: the fake the script talks to.
        action: WORKSPACE_ACTION.

    Returns:
        The exit status and the lines ``main`` printed.
    """
    env = {
        "KC_URL": "http://keycloak",
        "KC_PID": "1",
        "KC_REALM": "platform",
        "KC_WORKSPACES_CLIENT": WORKSPACES_CLIENT,
        "WORKSPACE": WS,
        "WORKSPACE_ACTION": action,
    }
    out = io.StringIO()
    with (
        mock.patch.dict(m.os.environ, env, clear=True),
        mock.patch.object(m, "Keycloak", lambda *args: kc),
        mock.patch.object(m, "container_credentials", lambda path: ("u", "p")),
        redirect_stdout(out),
    ):
        code = m.main()
    return code, out.getvalue().splitlines()


def owner_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith(f"{m.OWNER_LINE} ")]


class TestOwnerGroup(unittest.TestCase):
    def setUp(self) -> None:
        self.kc = FakeKeycloak(USERS)

    def test_apply_names_the_id_of_the_owner_group_it_created(self) -> None:
        code, lines = main_output(self.kc, "apply")
        self.assertEqual(code, 0)
        self.assertEqual(
            owner_lines(lines), [f"{m.OWNER_LINE} {owner_id(self.kc, WS)}"]
        )
        self.assertTrue(lines[-1].startswith("summary created="))
        _, again = main_output(self.kc, "apply")
        self.assertEqual(owner_lines(again), owner_lines(lines))
        self.assertIn("created=0 deleted=0", again[-1])

    def test_each_workspace_names_its_own_owner_group(self) -> None:
        m.apply(self.kc, OTHER_WS, WORKSPACES_CLIENT)
        main_output(self.kc, "apply")
        self.assertNotEqual(owner_id(self.kc, WS), owner_id(self.kc, OTHER_WS))
        self.assertEqual(m.owner_group(self.kc, WS), owner_id(self.kc, WS))
        self.assertEqual(m.owner_group(self.kc, OTHER_WS), owner_id(self.kc, OTHER_WS))

    def test_destroy_names_no_owner_group(self) -> None:
        main_output(self.kc, "apply")
        code, lines = main_output(self.kc, "destroy")
        self.assertEqual((code, owner_lines(lines)), (0, []))

    def test_negative_control_an_organization_without_owner_fails_the_apply(
        self,
    ) -> None:
        with mock.patch.object(m, "ROLES", tuple(r for r in m.ROLES if r != m.OWNER)):
            code, lines = main_output(self.kc, "apply")
        self.assertEqual(code, 1)
        self.assertEqual(lines, [f"failed the organization ws-{WS} has no Owner group"])


class TestDestroy(unittest.TestCase):
    def setUp(self) -> None:
        self.kc = FakeKeycloak(USERS)
        m.apply(self.kc, WS, WORKSPACES_CLIENT)
        m.apply(self.kc, OTHER_WS, WORKSPACES_CLIENT)

    def test_destroy_deletes_the_client_roles_and_then_the_organization(self) -> None:
        self.kc.writes.clear()
        m.destroy(self.kc, WS, WORKSPACES_CLIENT)
        deletes = [path for method, path, _ in self.kc.writes if method == "DELETE"]
        self.assertEqual(len(deletes), 6)
        self.assertTrue(deletes[-1].startswith("organizations/"))
        self.assertTrue(
            all(p.startswith(f"clients/{WORKSPACES_UUID}/roles/") for p in deletes[:-1])
        )
        self.assertEqual(len(self.kc.orgs), 1)
        self.assertEqual(
            sorted(self.kc.client_roles), sorted(f"{OTHER_WS}:{r}" for r in m.ROLES)
        )

    def test_destroy_counts_a_missing_organization_as_deleted(self) -> None:
        m.destroy(self.kc, WS, WORKSPACES_CLIENT)
        before = state(self.kc)
        lines = m.destroy(self.kc, WS, WORKSPACES_CLIENT)
        self.assertEqual(state(self.kc), before)
        self.assertTrue(all(line.startswith("gone ") for line in lines))

    def test_the_missing_check_catches_a_destroy_that_fails_on_a_missing_organization(
        self,
    ) -> None:
        m.destroy(self.kc, WS, WORKSPACES_CLIENT)
        with (
            mock.patch.object(m, "delete", strict_delete),
            self.assertRaises(m.KeycloakHTTPError),
        ):
            m.destroy(self.kc, WS, WORKSPACES_CLIENT)

    def test_a_destroy_stopped_at_any_step_finishes_when_run_again(self) -> None:
        for step in range(6):
            with self.subTest(step=step):
                kc = FakeKeycloak(USERS)
                m.apply(kc, WS, WORKSPACES_CLIENT)
                kc.writes.clear()
                kc.fail_at = step
                with self.assertRaises(m.KeycloakHTTPError):
                    m.destroy(kc, WS, WORKSPACES_CLIENT)
                m.destroy(kc, WS, WORKSPACES_CLIENT)
                self.assertEqual((kc.orgs, kc.client_roles), ({}, {}))


if __name__ == "__main__":
    unittest.main()
