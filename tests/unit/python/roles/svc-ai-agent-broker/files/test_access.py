from __future__ import annotations

import sys
import unittest

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/svc-ai-agent-broker/files/python"))

import access

GROUP = "/roles/web-app-hermes/agent-user"


class FakeKeycloak(access.Keycloak):
    def __init__(self, users, groups):
        super().__init__("https://auth", "realm", "admin", "pw", timeout=5)
        self.users = users
        self.groups = groups

    def _admin_token(self):
        return "token"

    def _get(self, path, query):
        if path == "/users":
            return self.users.get(query["email"], [])
        user_id = path.split("/")[2]
        return [{"path": path} for path in self.groups.get(user_id, [])]


class TestAllows(unittest.TestCase):
    def test_only_a_member_of_the_platform_group_is_allowed(self):
        keycloak = FakeKeycloak(
            {"a@x": [{"id": "1"}], "b@x": [{"id": "2"}]},
            {"1": [GROUP], "2": ["/roles/web-app-hermes/mcp"]},
        )
        self.assertTrue(keycloak.allows("A@x", GROUP))
        self.assertFalse(keycloak.allows("b@x", GROUP))

    def test_an_unknown_or_empty_email_is_refused(self):
        keycloak = FakeKeycloak({}, {})
        self.assertFalse(keycloak.allows("", GROUP))
        self.assertFalse(keycloak.allows("nobody@x", GROUP))

    def test_a_grant_between_two_checks_is_seen_by_the_second(self):
        keycloak = FakeKeycloak({"a@x": [{"id": "1"}]}, {"1": []})
        self.assertFalse(keycloak.allows("a@x", GROUP))
        keycloak.groups["1"] = [GROUP]
        self.assertTrue(keycloak.allows("a@x", GROUP))

    def test_a_revocation_between_two_checks_is_seen_by_the_second(self):
        keycloak = FakeKeycloak({"a@x": [{"id": "1"}]}, {"1": [GROUP]})
        self.assertTrue(keycloak.allows("a@x", GROUP))
        keycloak.groups["1"] = []
        self.assertFalse(keycloak.allows("a@x", GROUP))


if __name__ == "__main__":
    unittest.main()
