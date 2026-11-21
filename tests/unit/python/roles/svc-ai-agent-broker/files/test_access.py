from __future__ import annotations

import sys
import unittest

from utils.cache.yaml import load_yaml

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/svc-ai-agent-broker/files/python"))

import access

GROUP = "/roles/web-app-hermes/agent-user"
MAILBOX = load_yaml(PROJECT_ROOT / "group_vars/all/11_oidc.yml")[
    "_oidc_email_mailbox_attribute"
]


class FakeKeycloak(access.Keycloak):
    """
    Args:
        users: user id -> representation, as the admin API returns it.
        groups: user id -> group paths.
        email_attribute: the attribute the realm's email claim is mapped from.
        fuzzy: whether the search returns every user.
    """

    def __init__(self, users, groups, email_attribute="email", fuzzy=False):
        super().__init__("https://auth", "realm", "admin", "pw", 5, email_attribute)
        self.users = users
        self.groups = groups
        self.fuzzy = fuzzy
        self.queries = []

    def _admin_token(self):
        return "token"

    def _get(self, path, query):
        if path == "/users":
            self.queries.append(query)
            if self.fuzzy:
                return list(self.users.values())
            if "email" in query:
                return [
                    u
                    for u in self.users.values()
                    if (u.get("email") or "").lower() == query["email"]
                ]
            name, _, value = query["q"].partition(":")
            return [
                u
                for u in self.users.values()
                if value
                in [v.lower() for v in (u.get("attributes") or {}).get(name, [])]
            ]
        user_id = path.split("/")[2]
        return [{"path": path} for path in self.groups.get(user_id, [])]


class TestAllows(unittest.TestCase):
    def test_only_a_member_of_the_platform_group_is_allowed(self):
        keycloak = FakeKeycloak(
            {"1": {"id": "1", "email": "a@x"}, "2": {"id": "2", "email": "b@x"}},
            {"1": [GROUP], "2": ["/roles/web-app-hermes/mcp"]},
        )
        self.assertTrue(keycloak.allows("A@x", GROUP))
        self.assertFalse(keycloak.allows("b@x", GROUP))

    def test_an_unknown_or_empty_email_is_refused(self):
        keycloak = FakeKeycloak({}, {})
        self.assertFalse(keycloak.allows("", GROUP))
        self.assertFalse(keycloak.allows("nobody@x", GROUP))

    def test_a_grant_between_two_checks_is_seen_by_the_second(self):
        keycloak = FakeKeycloak({"1": {"id": "1", "email": "a@x"}}, {"1": []})
        self.assertFalse(keycloak.allows("a@x", GROUP))
        keycloak.groups["1"] = [GROUP]
        self.assertTrue(keycloak.allows("a@x", GROUP))

    def test_a_revocation_between_two_checks_is_seen_by_the_second(self):
        keycloak = FakeKeycloak({"1": {"id": "1", "email": "a@x"}}, {"1": [GROUP]})
        self.assertTrue(keycloak.allows("a@x", GROUP))
        keycloak.groups["1"] = []
        self.assertFalse(keycloak.allows("a@x", GROUP))


class TestMailboxPolicy(unittest.TestCase):
    def mailbox_realm(self, fuzzy=False):
        return FakeKeycloak(
            {
                "1": {
                    "id": "1",
                    "email": "biber@elsewhere.example",
                    "attributes": {MAILBOX: ["biber@platform.example"]},
                },
                "2": {
                    "id": "2",
                    "email": "other@elsewhere.example",
                    "attributes": {MAILBOX: ["other@platform.example"]},
                },
            },
            {"1": [GROUP], "2": []},
            email_attribute=MAILBOX,
            fuzzy=fuzzy,
        )

    def test_the_claimed_mailbox_finds_its_member(self):
        keycloak = self.mailbox_realm()
        self.assertTrue(keycloak.allows("Biber@platform.example", GROUP))
        self.assertEqual(
            keycloak.queries[-1],
            {"q": f"{MAILBOX}:biber@platform.example", "exact": "true"},
        )

    def test_the_secondary_address_is_not_what_the_claim_carries(self):
        self.assertFalse(self.mailbox_realm().allows("biber@elsewhere.example", GROUP))

    def test_a_search_that_returns_others_grants_none_of_their_groups(self):
        keycloak = self.mailbox_realm(fuzzy=True)
        self.assertTrue(keycloak.allows("biber@platform.example", GROUP))
        self.assertFalse(keycloak.allows("other@platform.example", GROUP))
        self.assertFalse(keycloak.allows("nobody@platform.example", GROUP))


if __name__ == "__main__":
    unittest.main()
