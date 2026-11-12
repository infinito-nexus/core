import contextlib
import io
import json
import os
import sys
import unittest
import unittest.mock as mock
import urllib.parse
from collections import Counter

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))
sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python/rbac"))

import realm_groups as m


class FakeKeycloak:
    def __init__(self):
        self.groups = {}
        self.parents = {}
        self.users = {}
        self.memberships = {}
        self.calls = []
        self.failing_joins = set()
        self.silent_joins = set()
        self.failing_creates = set()
        self._next = 0

    def _id(self, prefix):
        self._next += 1
        return f"{prefix}-{self._next}"

    def add_group(self, name, parent=""):
        group_id = self._id("g")
        self.groups[group_id] = {"id": group_id, "name": name}
        self.parents[group_id] = parent
        return group_id

    def add_user(self, username):
        user_id = self._id("u")
        self.users[user_id] = {"id": user_id, "username": username.lower()}
        self.memberships[user_id] = set()
        return user_id

    def path_of(self, group_id):
        names = []
        while group_id:
            names.append(self.groups[group_id]["name"])
            group_id = self.parents[group_id]
        return "/" + "/".join(reversed(names))

    def member_paths(self, user_id):
        return {self.path_of(g) for g in self.memberships[user_id]}

    def _subgroups(self, parent):
        return [
            dict(g) for gid, g in self.groups.items() if self.parents[gid] == parent
        ]

    def _create(self, parent, payload):
        name = payload["name"]
        if name in self.failing_creates:
            raise m.KeycloakError(f"POST {name}: HTTP 500")
        if any(g["name"] == name for g in self._subgroups(parent)):
            raise m.KeycloakError(f"POST {name}: HTTP 409")
        return None, self.add_group(name, parent)

    def children(self, group_id):
        self.calls.append(("CHILDREN", group_id))
        return self._subgroups(group_id)

    def call(self, method, path, payload=None, timeout=60):
        self.calls.append((method, path.split("?", 1)[0]))
        route, _, query = path.partition("?")
        parts = route.split("/")
        if method == "GET" and route == "groups":
            return self._subgroups(""), ""
        if method == "POST" and route == "groups":
            return self._create("", payload)
        if method == "POST" and parts[0] == "groups" and parts[2:] == ["children"]:
            return self._create(parts[1], payload)
        if method == "GET" and route == "users":
            params = urllib.parse.parse_qs(query)
            assert params["exact"] == ["true"]
            wanted = params["username"][0].lower()
            return [dict(u) for u in self.users.values() if wanted in u["username"]], ""
        if method == "GET" and parts[0] == "users" and parts[2:] == ["groups"]:
            return [dict(self.groups[g]) for g in self.memberships[parts[1]]], ""
        if method == "PUT" and parts[0] == "users" and parts[2] == "groups":
            user_id, group_id = parts[1], parts[3]
            if user_id in self.failing_joins:
                raise m.KeycloakError(f"PUT {route}: HTTP 500")
            if user_id not in self.silent_joins:
                self.memberships[user_id].add(group_id)
            return None, ""
        raise AssertionError(f"unexpected call {method} {path}")

    def count(self, method):
        return sum(1 for call_method, _ in self.calls if call_method == method)


SPEC = [
    {"path": "roles/web-app-a/administrator", "members": ["administrator"]},
    {"path": "roles/web-app-a/mcp", "members": ["agent", "Administrator"]},
    {"path": "roles/web-app-b/administrator", "members": ["administrator"]},
]


class TestConverge(unittest.TestCase):
    def test_a_fresh_realm_gets_every_group_once_and_every_membership(self):
        kc = FakeKeycloak()
        admin = kc.add_user("administrator")
        agent = kc.add_user("agent")
        lines = m.converge(kc, SPEC)
        self.assertEqual(
            lines,
            [
                "created group /roles/web-app-a/administrator",
                "joined member /roles/web-app-a/administrator administrator",
                "created group /roles/web-app-a/mcp",
                "joined member /roles/web-app-a/mcp agent",
                "joined member /roles/web-app-a/mcp Administrator",
                "created group /roles/web-app-b/administrator",
                "joined member /roles/web-app-b/administrator administrator",
            ],
        )
        self.assertEqual(
            sorted(kc.path_of(g) for g in kc.groups),
            [
                "/roles",
                "/roles/web-app-a",
                "/roles/web-app-a/administrator",
                "/roles/web-app-a/mcp",
                "/roles/web-app-b",
                "/roles/web-app-b/administrator",
            ],
        )
        self.assertEqual(
            kc.member_paths(admin),
            {
                "/roles/web-app-a/administrator",
                "/roles/web-app-a/mcp",
                "/roles/web-app-b/administrator",
            },
        )
        self.assertEqual(kc.member_paths(agent), {"/roles/web-app-a/mcp"})

    def test_a_converged_realm_is_left_alone_and_listed_once_per_parent(self):
        kc = FakeKeycloak()
        kc.add_user("administrator")
        kc.add_user("agent")
        m.converge(kc, SPEC)
        kc.calls.clear()
        lines = m.converge(kc, SPEC)
        self.assertTrue(all(line.startswith("unchanged ") for line in lines), lines)
        self.assertEqual(kc.count("POST"), 0)
        self.assertEqual(kc.count("PUT"), 0)
        listings = Counter(call for call in kc.calls if call[0] == "CHILDREN")
        self.assertEqual(set(listings.values()), {1})
        self.assertEqual(len(listings), 3)
        self.assertEqual(kc.calls.count(("GET", "groups")), 1)
        self.assertEqual(kc.calls.count(("GET", "users")), 2)

    def test_only_the_missing_leaf_of_an_existing_tree_is_created(self):
        kc = FakeKeycloak()
        kc.add_user("administrator")
        root = kc.add_group("roles")
        app = kc.add_group("web-app-a", root)
        kc.add_group("administrator", app)
        spec = [
            {"path": "roles/web-app-a/administrator", "members": []},
            {"path": "roles/web-app-a/editor", "members": []},
        ]
        lines = m.converge(kc, spec)
        self.assertEqual(
            lines,
            [
                "unchanged group /roles/web-app-a/administrator",
                "created group /roles/web-app-a/editor",
            ],
        )
        self.assertEqual(kc.count("POST"), 1)

    def test_a_tenant_path_of_four_segments_is_created_in_full(self):
        kc = FakeKeycloak()
        spec = [{"path": "roles/web-app-a/example.org/editor", "members": []}]
        self.assertEqual(
            m.converge(kc, spec), ["created group /roles/web-app-a/example.org/editor"]
        )
        self.assertIn(
            "/roles/web-app-a/example.org/editor", {kc.path_of(g) for g in kc.groups}
        )

    def test_only_the_exact_username_is_joined(self):
        kc = FakeKeycloak()
        other = kc.add_user("contact2")
        target = kc.add_user("contact")
        spec = [{"path": "roles/web-app-a/administrator", "members": ["Contact"]}]
        m.converge(kc, spec)
        self.assertEqual(kc.member_paths(target), {"/roles/web-app-a/administrator"})
        self.assertEqual(kc.member_paths(other), set())

    def test_an_absent_member_is_named_and_the_other_groups_still_converge(self):
        kc = FakeKeycloak()
        admin = kc.add_user("administrator")
        spec = [
            {"path": "roles/web-app-a/administrator", "members": ["ghost"]},
            {"path": "roles/web-app-b/administrator", "members": ["administrator"]},
        ]
        lines = m.converge(kc, spec)
        self.assertIn("missing member /roles/web-app-a/administrator ghost", lines)
        self.assertEqual(kc.member_paths(admin), {"/roles/web-app-b/administrator"})

    def test_a_failed_join_is_named_and_the_other_members_still_join(self):
        kc = FakeKeycloak()
        admin = kc.add_user("administrator")
        agent = kc.add_user("agent")
        kc.failing_joins.add(admin)
        spec = [{"path": "roles/web-app-a/mcp", "members": ["administrator", "agent"]}]
        with contextlib.redirect_stderr(io.StringIO()) as err:
            lines = m.converge(kc, spec)
        self.assertIn("failed member /roles/web-app-a/mcp administrator", lines)
        self.assertIn("joined member /roles/web-app-a/mcp agent", lines)
        self.assertEqual(kc.member_paths(agent), {"/roles/web-app-a/mcp"})
        self.assertIn("HTTP 500", err.getvalue())

    def test_a_join_the_membership_listing_does_not_show_fails(self):
        kc = FakeKeycloak()
        admin = kc.add_user("administrator")
        kc.silent_joins.add(admin)
        spec = [{"path": "roles/web-app-a/administrator", "members": ["administrator"]}]
        with contextlib.redirect_stderr(io.StringIO()):
            lines = m.converge(kc, spec)
        self.assertEqual(
            lines[-1], "failed member /roles/web-app-a/administrator administrator"
        )

    def test_a_failed_group_is_named_and_the_other_groups_still_converge(self):
        kc = FakeKeycloak()
        kc.add_user("administrator")
        kc.failing_creates.add("web-app-a")
        spec = [
            {"path": "roles/web-app-a/administrator", "members": ["administrator"]},
            {"path": "roles/web-app-b/administrator", "members": ["administrator"]},
        ]
        with contextlib.redirect_stderr(io.StringIO()):
            lines = m.converge(kc, spec)
        self.assertEqual(
            lines,
            [
                "failed group /roles/web-app-a/administrator",
                "created group /roles/web-app-b/administrator",
                "joined member /roles/web-app-b/administrator administrator",
            ],
        )


class TestMain(unittest.TestCase):
    def _run(self, kc, stdin):
        out = io.StringIO()
        env = {"KC_URL": "http://kc", "KC_PID": "1", "KC_REALM": "r"}
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(m, "Keycloak", lambda *args: kc),
            mock.patch.object(m, "container_credentials", lambda path: ("a", "p")),
            mock.patch.object(sys, "stdin", io.StringIO(stdin)),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            code = m.main()
        return code, out.getvalue().splitlines()

    def test_the_summary_counts_every_outcome_and_a_clean_run_passes(self):
        kc = FakeKeycloak()
        kc.add_user("administrator")
        kc.add_user("agent")
        code, lines = self._run(kc, json.dumps(SPEC))
        self.assertEqual(code, 0)
        self.assertEqual(
            lines[-1], "summary created=3 joined=4 unchanged=0 missing=0 failed=0"
        )
        code, lines = self._run(kc, json.dumps(SPEC))
        self.assertEqual(code, 0)
        self.assertEqual(
            lines[-1], "summary created=0 joined=0 unchanged=7 missing=0 failed=0"
        )

    def test_a_missing_member_fails_the_run(self):
        kc = FakeKeycloak()
        spec = [{"path": "roles/web-app-a/administrator", "members": ["ghost"]}]
        code, lines = self._run(kc, json.dumps(spec))
        self.assertEqual(code, 1)
        self.assertIn("missing member /roles/web-app-a/administrator ghost", lines)

    def test_a_failed_member_fails_the_run(self):
        kc = FakeKeycloak()
        kc.failing_joins.add(kc.add_user("administrator"))
        spec = [{"path": "roles/web-app-a/administrator", "members": ["administrator"]}]
        code, lines = self._run(kc, json.dumps(spec))
        self.assertEqual(code, 1)
        self.assertIn(
            "failed member /roles/web-app-a/administrator administrator", lines
        )

    def test_a_malformed_spec_fails_before_any_call(self):
        kc = FakeKeycloak()
        code, lines = self._run(kc, "not json")
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("listing-failed"))
        self.assertEqual(kc.calls, [])


if __name__ == "__main__":
    unittest.main()
