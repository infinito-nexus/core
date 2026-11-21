"""Unit tests for ``utils.domains.served``."""

from __future__ import annotations

import unittest

from utils.domains.served import (
    declares_served,
    is_member_label,
    served_domains,
    served_owners,
    served_specs,
)

APP = "web-app-wordpress"
OTHER = "web-app-other"
PARENT = "user.blog.main.test"
BIBER = "biber.user.blog.main.test"
MAPACHE = "mapache.user.blog.main.test"
WILDCARD = "*.user.blog.main.test"
APPLICATIONS = {
    APP: {
        "domains": {
            "canonical": ["blog.main.test"],
            "served": [{"parent": PARENT, "role": "site-owner"}],
        }
    },
    OTHER: {"domains": {"canonical": ["other.main.test"]}},
}
USERS = {
    "biber": {"username": "biber", "roles": ["site-owner"]},
    "mapache": {"username": "mapache", "application_roles": {APP: ["site-owner"]}},
    "guest": {"username": "guest", "roles": []},
}


def _served(wildcard, known=("blog.main.test",), users=USERS):
    return served_domains(
        APPLICATIONS,
        users,
        [APP, OTHER, "web-app-absent"],
        wildcard_certificate=lambda app: wildcard,
        known_domains=list(known),
    )


class TestIsMemberLabel(unittest.TestCase):
    def test_keycloak_usernames_name_member_hosts(self):
        for username in ("biber", "mapache", "a1b2", "abcd0wordpress", "a" * 63):
            with self.subTest(username=username):
                self.assertTrue(is_member_label(username))

    def test_everything_keycloak_or_wordpress_refuses_names_no_host(self):
        for username in (
            "harry.beaver",
            "harry_beaver",
            "harry-beaver",
            "xn--bber-zra",
            "Biber",
            "biber0",
            "ab0cd",
            "a" * 64,
            "",
            "www",
            "admin",
            "blog",
            "files",
        ):
            with self.subTest(username=username):
                self.assertFalse(is_member_label(username))


class TestServedSpecs(unittest.TestCase):
    def test_an_application_without_the_key_serves_nothing(self):
        cfg = {"domains": {"canonical": ["a"]}}
        self.assertEqual(([], []), served_specs("x", cfg))
        self.assertEqual(([], []), served_specs("x", {}))

    def test_every_entry_yields_its_lowercase_parent_and_role(self):
        cfg = {"domains": {"served": [{"parent": "User.Blog.Main.Test", "role": "r"}]}}
        self.assertEqual(([(PARENT, "r")], []), served_specs("x", cfg))

    def test_a_malformed_declaration_is_a_problem_not_an_exception(self):
        for served in (
            PARENT,
            [{"parent": PARENT}],
            [{"parent": PARENT, "role": "r", "extra": 1}],
            [{"parent": "", "role": "r"}],
            [{"parent": "user.blog.{{ DOMAIN_PRIMARY }}", "role": "r"}],
        ):
            with self.subTest(served=served):
                specs, problems = served_specs("x", {"domains": {"served": served}})
                self.assertEqual([], specs)
                self.assertEqual(1, len(problems))


class TestServedDomains(unittest.TestCase):
    def test_a_wildcard_certificate_serves_one_wildcard_for_all_members(self):
        self.assertEqual(
            {
                "entries": [
                    {
                        "name": WILDCARD,
                        "application_id": APP,
                        "members": ["biber", "mapache"],
                        "hosts": [BIBER, MAPACHE],
                    }
                ],
                "problems": [],
            },
            _served(True),
        )

    def test_a_wildcard_serves_even_without_a_member(self):
        self.assertEqual(
            [WILDCARD], [entry["name"] for entry in _served(True, users={})["entries"]]
        )

    def test_without_a_wildcard_certificate_every_member_host_is_a_name(self):
        self.assertEqual(
            [
                {
                    "name": BIBER,
                    "application_id": APP,
                    "members": ["biber"],
                    "hosts": [BIBER],
                },
                {
                    "name": MAPACHE,
                    "application_id": APP,
                    "members": ["mapache"],
                    "hosts": [MAPACHE],
                },
            ],
            _served(False)["entries"],
        )

    def test_a_member_whose_username_names_no_host_is_a_problem(self):
        dotted = {"username": "harry.beaver", "roles": ["site-owner"]}
        result = _served(False, users={**USERS, "dotted": dotted})
        names = [entry["name"] for entry in result["entries"]]
        self.assertEqual([BIBER, MAPACHE], names)
        self.assertEqual(1, len(result["problems"]))
        self.assertIn("harry.beaver", result["problems"][0])

    def test_a_served_name_that_repeats_a_known_domain_is_a_problem(self):
        for wildcard, known in ((False, BIBER), (True, WILDCARD)):
            with self.subTest(known=known):
                result = _served(wildcard, known=(known,))
                self.assertNotIn(known, [entry["name"] for entry in result["entries"]])
                self.assertEqual(1, len(result["problems"]))

    def test_the_wildcard_decision_is_made_per_application(self):
        seen = []

        def wildcard(app_cfg):
            seen.append(app_cfg)
            return False

        served_domains(
            APPLICATIONS,
            USERS,
            [APP],
            wildcard_certificate=wildcard,
            known_domains=[],
        )
        self.assertEqual([APPLICATIONS[APP]], seen)


class TestServedOwners(unittest.TestCase):
    def test_owners_come_from_the_constructor_fact(self):
        fact = [{"name": "*.User.Blog.Main.Test", "application_id": APP}]
        self.assertEqual(
            {WILDCARD: APP}, served_owners({"CURRENT_PLAY_SERVED_DOMAINS": fact})
        )

    def test_no_owner_before_the_constructor_set_the_fact(self):
        self.assertEqual({}, served_owners({}))


class TestDeclaresServed(unittest.TestCase):
    def test_only_a_declaring_application_counts(self):
        self.assertTrue(declares_served(APPLICATIONS, [APP]))
        self.assertFalse(declares_served(APPLICATIONS, [OTHER, "web-app-absent"]))


if __name__ == "__main__":
    unittest.main()
