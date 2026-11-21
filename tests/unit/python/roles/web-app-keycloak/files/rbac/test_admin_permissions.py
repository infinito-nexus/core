import sys
import unittest
import urllib.parse
from copy import deepcopy

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))
sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python/rbac"))

import admin_permissions as m

CLIENT = "ap-1"
BASE = f"clients/{CLIENT}/authz/resource-server"
PLATFORM = "/roles/web-svc-access-request/administrator"
BLOG_ADMIN = "/roles/web-app-blog/administrator"
BLOG_EDITOR = "/roles/web-app-blog/editor"
BLOG_READER = "/roles/web-app-blog/reader"


class FakeKeycloak:
    def __init__(self, groups, admin_permissions=True):
        self.groups = {path: f"g{index}" for index, path in enumerate(groups)}
        self.entries = {}
        self.writes = []
        self.admin_permissions = admin_permissions
        self._next = 0

    def by_name(self, name):
        return next(e for e in self.entries.values() if e["name"] == name)

    def call(self, method, path, payload=None, timeout=60):
        route, _, query = path.partition("?")
        if method != "GET":
            self.writes.append((method, route, deepcopy(payload)))
        if method == "GET" and route == "clients":
            wanted = urllib.parse.parse_qs(query)["clientId"][0]
            found = (
                [{"id": CLIENT, "clientId": wanted}] if self.admin_permissions else []
            )
            return found, ""
        if method == "GET" and route.startswith("group-by-path/"):
            group = "/" + urllib.parse.unquote(route.removeprefix("group-by-path/"))
            if group not in self.groups:
                raise m.KeycloakError(f"GET cymais/{route}: HTTP 404")
            return {"id": self.groups[group], "path": group}, ""
        if method == "GET" and route == f"{BASE}/policy":
            first = int(urllib.parse.parse_qs(query)["first"][0])
            listed = [
                {k: e[k] for k in ("id", "name", "type", "description")}
                for e in self.entries.values()
            ]
            return listed[first : first + m.PAGE], ""
        if method == "POST" and route in (
            f"{BASE}/policy/group",
            f"{BASE}/permission/scope",
        ):
            self._next += 1
            entry_id = f"p{self._next}"
            self.entries[entry_id] = {**deepcopy(payload), "id": entry_id}
            return {**deepcopy(payload), "id": entry_id}, ""
        if method == "PUT":
            entry_id = route.rsplit("/", 1)[1]
            self.entries[entry_id] = deepcopy(payload)
            return None, ""
        if method == "DELETE" and route.startswith(f"{BASE}/policy/"):
            del self.entries[route.rsplit("/", 1)[1]]
            return None, ""
        raise AssertionError(f"unexpected call {method} {path}")


def spec(approvers):
    return {"prefix": "access-request", "approvers": approvers}


SPEC = spec(
    [
        {"approver": PLATFORM, "groups": [BLOG_ADMIN, BLOG_EDITOR]},
        {"approver": BLOG_ADMIN, "groups": [BLOG_EDITOR]},
    ]
)


class TestAdminPermissions(unittest.TestCase):
    def setUp(self):
        self.kc = FakeKeycloak([PLATFORM, BLOG_ADMIN, BLOG_EDITOR, BLOG_READER])

    def test_a_fresh_realm_gets_a_policy_and_two_permissions_per_approver(self):
        lines = m.converge(self.kc, SPEC)

        self.assertEqual(
            6, len([line for line in lines if line.startswith("created ")])
        )
        policy = self.kc.by_name(f"access-request:{BLOG_ADMIN}")
        self.assertEqual("group", policy["type"])
        self.assertEqual([{"id": "g1", "extendChildren": False}], policy["groups"])
        users = self.kc.by_name(f"access-request:{BLOG_ADMIN}:users")
        self.assertEqual("Users", users["resourceType"])
        self.assertEqual([], users["resources"])
        self.assertEqual(["view", "manage-group-membership"], users["scopes"])
        self.assertEqual([policy["id"]], users["policies"])
        groups = self.kc.by_name(f"access-request:{BLOG_ADMIN}:groups")
        self.assertEqual("Groups", groups["resourceType"])
        self.assertEqual(["g2"], groups["resources"])
        self.assertEqual(["view", "manage-membership"], groups["scopes"])
        self.assertEqual([policy["id"]], groups["policies"])

    def test_an_application_administrator_may_not_grant_its_own_group(self):
        m.converge(self.kc, SPEC)

        groups = self.kc.by_name(f"access-request:{BLOG_ADMIN}:groups")
        self.assertNotIn(self.kc.groups[BLOG_ADMIN], groups["resources"])
        platform = self.kc.by_name(f"access-request:{PLATFORM}:groups")
        self.assertEqual(["g1", "g2"], platform["resources"])

    def test_a_second_run_changes_nothing(self):
        m.converge(self.kc, SPEC)
        self.kc.writes.clear()

        lines = m.converge(self.kc, SPEC)

        self.assertEqual([], self.kc.writes)
        self.assertTrue(all(line.startswith("unchanged ") for line in lines), lines)

    def test_a_new_delegated_group_updates_the_group_permission(self):
        m.converge(self.kc, SPEC)
        wider = spec(
            [
                {"approver": PLATFORM, "groups": [BLOG_ADMIN, BLOG_EDITOR]},
                {"approver": BLOG_ADMIN, "groups": [BLOG_EDITOR, BLOG_READER]},
            ]
        )

        lines = m.converge(self.kc, wider)

        self.assertIn(f"updated permission access-request:{BLOG_ADMIN}:groups", lines)
        groups = self.kc.by_name(f"access-request:{BLOG_ADMIN}:groups")
        self.assertEqual(["g2", "g3"], groups["resources"])

    def test_a_recreated_policy_rewrites_the_permissions_that_name_it(self):
        m.converge(self.kc, SPEC)
        del self.kc.entries[self.kc.by_name(f"access-request:{BLOG_ADMIN}")["id"]]

        lines = m.converge(self.kc, SPEC)

        policy = self.kc.by_name(f"access-request:{BLOG_ADMIN}")
        self.assertIn(f"created policy access-request:{BLOG_ADMIN}", lines)
        self.assertIn(f"updated permission access-request:{BLOG_ADMIN}:users", lines)
        users = self.kc.by_name(f"access-request:{BLOG_ADMIN}:users")
        self.assertEqual([policy["id"]], users["policies"])

    def test_an_approver_the_spec_drops_loses_its_entries_permissions_first(self):
        m.converge(self.kc, SPEC)
        self.kc.writes.clear()

        lines = m.converge(self.kc, spec([SPEC["approvers"][0]]))

        deleted = [line for line in lines if line.startswith("deleted ")]
        self.assertEqual(
            [
                f"deleted permission access-request:{BLOG_ADMIN}:groups",
                f"deleted permission access-request:{BLOG_ADMIN}:users",
                f"deleted policy access-request:{BLOG_ADMIN}",
            ],
            deleted,
        )
        self.assertEqual(
            {
                f"access-request:{PLATFORM}",
                f"access-request:{PLATFORM}:users",
                f"access-request:{PLATFORM}:groups",
            },
            {e["name"] for e in self.kc.entries.values()},
        )

    def test_entries_outside_the_prefix_stay_untouched(self):
        self.kc.entries["manual"] = {
            "id": "manual",
            "name": "hand-made",
            "type": "group",
            "description": "",
        }

        m.converge(self.kc, SPEC)

        self.assertIn("manual", self.kc.entries)

    def test_a_missing_approver_group_is_reported_and_gets_no_entries(self):
        kc = FakeKeycloak([PLATFORM, BLOG_EDITOR])

        lines = m.converge(kc, SPEC)

        self.assertIn(f"missing group {BLOG_ADMIN}", lines)
        self.assertNotIn(
            f"access-request:{BLOG_ADMIN}", {e["name"] for e in kc.entries.values()}
        )

    def test_a_missing_target_group_is_left_out_of_the_resources(self):
        kc = FakeKeycloak([PLATFORM, BLOG_ADMIN])

        lines = m.converge(kc, SPEC)

        self.assertIn(f"missing group {BLOG_EDITOR}", lines)
        self.assertEqual(
            ["g1"], kc.by_name(f"access-request:{PLATFORM}:groups")["resources"]
        )
        self.assertNotIn(
            f"access-request:{BLOG_ADMIN}:groups",
            {e["name"] for e in kc.entries.values()},
        )

    def test_a_realm_without_admin_permissions_fails(self):
        kc = FakeKeycloak([PLATFORM], admin_permissions=False)

        with self.assertRaises(m.KeycloakError):
            m.converge(kc, SPEC)


if __name__ == "__main__":
    unittest.main()
