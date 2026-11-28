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
SHOP_ADMIN = "/roles/web-app-shop/administrator"
SHOP_CLERK = "/roles/web-app-shop/clerk"
GROUPS = [PLATFORM, BLOG_ADMIN, BLOG_EDITOR, BLOG_READER, SHOP_ADMIN, SHOP_CLERK]
APPROVERS = "access-request:approvers"
USERS = "access-request:users"
PLATFORM_ONLY = f"access-request:{PLATFORM}"
BLOG_SET = f"access-request:{BLOG_ADMIN},{PLATFORM}"
SHOP_SET = f"access-request:{SHOP_ADMIN},{PLATFORM}"


class FakeKeycloak:
    def __init__(self, groups, admin_permissions=True):
        self.groups = {path: f"g{index}" for index, path in enumerate(groups)}
        self.entries = {}
        self.writes = []
        self.admin_permissions = admin_permissions
        self._next = 0

    def by_name(self, name):
        return next(e for e in self.entries.values() if e["name"] == name)

    def names(self):
        return {e["name"] for e in self.entries.values()}

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

    def plant_per_approver_layout(self, approvers):
        """Write one policy with its own users and groups permissions per approver.

        Args:
            approvers: ``(approver path, [group path, ...])`` pairs.
        """
        for index, (approver, groups) in enumerate(approvers):
            name = f"access-request:{approver}"
            policy_id = f"old{index}"
            self.entries[policy_id] = {
                "id": policy_id,
                "name": name,
                "type": "group",
                "description": "",
                "groups": [{"id": self.groups[approver], "extendChildren": False}],
            }
            for suffix, resource_type, resources, scopes in (
                ("users", "Users", [], m.USER_SCOPES),
                ("groups", "Groups", [self.groups[g] for g in groups], m.GROUP_SCOPES),
            ):
                self.entries[f"{policy_id}{suffix}"] = {
                    "id": f"{policy_id}{suffix}",
                    "name": f"{name}:{suffix}",
                    "type": "scope",
                    "description": "",
                    "resourceType": resource_type,
                    "resources": sorted(resources),
                    "scopes": scopes,
                    "policies": [policy_id],
                }

    def may(self, member_of, resource_type, resource, scope):
        """Return whether a member of ``member_of`` holds ``scope`` on ``resource``.

        Args:
            member_of: paths of the groups the acting user belongs to.
            resource_type: ``Users`` or ``Groups``.
            resource: Keycloak id of the user or group acted on.
            scope: the scope the call needs.
        """
        ids = {self.groups[path] for path in member_of}
        permissions = [
            e
            for e in self.entries.values()
            if e["type"] == "scope"
            and e["resourceType"] == resource_type
            and scope in e["scopes"]
        ]
        specific = [p for p in permissions if resource in p["resources"]]
        applying = specific or [p for p in permissions if not p["resources"]]

        def grants(policy_id):
            return any(g["id"] in ids for g in self.entries[policy_id]["groups"])

        return bool(applying) and all(
            all(grants(policy_id) for policy_id in p["policies"]) for p in applying
        )

    def may_join(self, member_of, group):
        return self.may(
            member_of, "Users", "mapache", "manage-group-membership"
        ) and self.may(member_of, "Groups", self.groups[group], "manage-membership")


def spec(approvers):
    return {"prefix": "access-request", "approvers": approvers}


SPEC = spec(
    [
        {
            "approver": PLATFORM,
            "groups": [BLOG_ADMIN, BLOG_EDITOR, SHOP_ADMIN, SHOP_CLERK],
        },
        {"approver": BLOG_ADMIN, "groups": [BLOG_EDITOR]},
        {"approver": SHOP_ADMIN, "groups": [SHOP_CLERK]},
    ]
)


class TestAdminPermissions(unittest.TestCase):
    def setUp(self):
        self.kc = FakeKeycloak(GROUPS)

    def test_a_fresh_realm_gets_one_users_permission_and_one_per_approver_set(self):
        lines = m.converge(self.kc, SPEC)

        self.assertEqual(
            8, len([line for line in lines if line.startswith("created ")])
        )
        approvers = self.kc.by_name(APPROVERS)
        self.assertEqual(
            [
                {"id": self.kc.groups[path], "extendChildren": False}
                for path in (BLOG_ADMIN, SHOP_ADMIN, PLATFORM)
            ],
            approvers["groups"],
        )
        users = self.kc.by_name(USERS)
        self.assertEqual("Users", users["resourceType"])
        self.assertEqual([], users["resources"])
        self.assertEqual(["view", "manage-group-membership"], users["scopes"])
        self.assertEqual([approvers["id"]], users["policies"])
        blog = self.kc.by_name(f"{BLOG_SET}:groups")
        self.assertEqual("Groups", blog["resourceType"])
        self.assertEqual([self.kc.groups[BLOG_EDITOR]], blog["resources"])
        self.assertEqual(["view", "manage-membership"], blog["scopes"])
        self.assertEqual([self.kc.by_name(BLOG_SET)["id"]], blog["policies"])
        self.assertEqual(
            sorted([self.kc.groups[BLOG_ADMIN], self.kc.groups[SHOP_ADMIN]]),
            self.kc.by_name(f"{PLATFORM_ONLY}:groups")["resources"],
        )

    def test_every_user_and_group_carries_exactly_one_permission(self):
        m.converge(self.kc, SPEC)

        permissions = [e for e in self.kc.entries.values() if e["type"] == "scope"]
        self.assertEqual(
            1,
            len(
                [
                    p
                    for p in permissions
                    if p["resourceType"] == "Users" and not p["resources"]
                ]
            ),
        )
        granted = [
            group
            for p in permissions
            if p["resourceType"] == "Groups"
            for group in p["resources"]
        ]
        self.assertEqual(sorted(set(granted)), sorted(granted))

    def test_an_application_administrator_grants_only_its_non_administrator_roles(
        self,
    ):
        m.converge(self.kc, SPEC)

        self.assertTrue(self.kc.may_join({BLOG_ADMIN}, BLOG_EDITOR))
        self.assertFalse(self.kc.may_join({BLOG_ADMIN}, BLOG_ADMIN))
        self.assertFalse(self.kc.may_join({BLOG_ADMIN}, SHOP_CLERK))
        self.assertFalse(self.kc.may_join({BLOG_ADMIN}, BLOG_READER))

    def test_the_platform_administrator_grants_every_listed_role(self):
        m.converge(self.kc, SPEC)

        for group in (BLOG_ADMIN, BLOG_EDITOR, SHOP_ADMIN, SHOP_CLERK):
            self.assertTrue(self.kc.may_join({PLATFORM}, group), group)

    def test_a_user_outside_every_approver_group_grants_nothing(self):
        m.converge(self.kc, SPEC)

        self.assertFalse(self.kc.may_join({BLOG_READER}, BLOG_EDITOR))

    def test_per_approver_permissions_lock_out_the_application_administrator(self):
        self.kc.plant_per_approver_layout(
            [(entry["approver"], entry["groups"]) for entry in SPEC["approvers"]]
        )

        self.assertFalse(self.kc.may_join({BLOG_ADMIN}, BLOG_EDITOR))

    def test_converging_the_per_approver_layout_unlocks_the_application_administrator(
        self,
    ):
        self.kc.plant_per_approver_layout(
            [(entry["approver"], entry["groups"]) for entry in SPEC["approvers"]]
        )

        lines = m.converge(self.kc, SPEC)

        self.assertIn(f"deleted permission access-request:{BLOG_ADMIN}:users", lines)
        self.assertIn(f"deleted policy access-request:{BLOG_ADMIN}", lines)
        self.assertIn(f"deleted permission access-request:{PLATFORM}:users", lines)
        self.assertIn(f"updated permission {PLATFORM_ONLY}:groups", lines)
        self.assertTrue(self.kc.may_join({BLOG_ADMIN}, BLOG_EDITOR))
        self.assertFalse(self.kc.may_join({BLOG_ADMIN}, BLOG_ADMIN))

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
                {
                    "approver": PLATFORM,
                    "groups": [BLOG_ADMIN, BLOG_EDITOR, BLOG_READER],
                },
                {"approver": BLOG_ADMIN, "groups": [BLOG_EDITOR, BLOG_READER]},
            ]
        )

        lines = m.converge(self.kc, wider)

        self.assertIn(f"updated permission {BLOG_SET}:groups", lines)
        self.assertEqual(
            [self.kc.groups[BLOG_EDITOR], self.kc.groups[BLOG_READER]],
            self.kc.by_name(f"{BLOG_SET}:groups")["resources"],
        )
        self.assertTrue(self.kc.may_join({BLOG_ADMIN}, BLOG_READER))

    def test_a_recreated_policy_rewrites_the_permissions_that_name_it(self):
        m.converge(self.kc, SPEC)
        del self.kc.entries[self.kc.by_name(BLOG_SET)["id"]]

        lines = m.converge(self.kc, SPEC)

        self.assertIn(f"created policy {BLOG_SET}", lines)
        self.assertIn(f"updated permission {BLOG_SET}:groups", lines)
        self.assertEqual(
            [self.kc.by_name(BLOG_SET)["id"]],
            self.kc.by_name(f"{BLOG_SET}:groups")["policies"],
        )

    def test_an_approver_the_spec_drops_loses_its_entries_permissions_first(self):
        m.converge(self.kc, SPEC)
        self.kc.writes.clear()

        lines = m.converge(self.kc, spec(SPEC["approvers"][:2]))

        deleted = [line for line in lines if line.startswith("deleted ")]
        self.assertEqual(
            [
                f"deleted permission {SHOP_SET}:groups",
                f"deleted policy {SHOP_SET}",
            ],
            deleted,
        )
        self.assertIn(f"updated policy {APPROVERS}", lines)
        self.assertFalse(self.kc.may_join({SHOP_ADMIN}, SHOP_CLERK))
        self.assertTrue(self.kc.may_join({PLATFORM}, SHOP_CLERK))

    def test_entries_outside_the_prefix_stay_untouched(self):
        self.kc.entries["manual"] = {
            "id": "manual",
            "name": "hand-made",
            "type": "group",
            "description": "",
        }

        m.converge(self.kc, SPEC)

        self.assertIn("manual", self.kc.entries)

    def test_a_missing_approver_group_is_reported_and_admits_no_one(self):
        kc = FakeKeycloak([PLATFORM, BLOG_EDITOR, SHOP_ADMIN, SHOP_CLERK])

        lines = m.converge(kc, SPEC)

        self.assertIn(f"missing group {BLOG_ADMIN}", lines)
        self.assertNotIn(BLOG_SET, kc.names())
        self.assertTrue(kc.may_join({PLATFORM}, BLOG_EDITOR))
        self.assertTrue(kc.may_join({SHOP_ADMIN}, SHOP_CLERK))

    def test_a_missing_target_group_is_left_out_of_the_resources(self):
        kc = FakeKeycloak([PLATFORM, BLOG_ADMIN])

        lines = m.converge(kc, spec(SPEC["approvers"][:2]))

        self.assertIn(f"missing group {BLOG_EDITOR}", lines)
        self.assertEqual(
            [kc.groups[BLOG_ADMIN]], kc.by_name(f"{PLATFORM_ONLY}:groups")["resources"]
        )
        self.assertNotIn(f"{BLOG_SET}:groups", kc.names())
        self.assertIn(USERS, kc.names())

    def test_a_realm_without_admin_permissions_fails(self):
        kc = FakeKeycloak([PLATFORM], admin_permissions=False)

        with self.assertRaises(m.KeycloakError):
            m.converge(kc, SPEC)


if __name__ == "__main__":
    unittest.main()
