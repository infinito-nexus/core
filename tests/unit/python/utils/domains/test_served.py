"""Unit tests for ``utils.domains.served``."""

from __future__ import annotations

import unittest

from utils.domains.served import (
    declares_served,
    is_member_label,
    served_domains,
    served_owners,
    served_parent,
    served_specs,
)

APP = "web-app-wordpress"
OTHER = "web-app-other"
PRIMARY = "main.test"
PARENT = "user.blog.main.test"
BIBER = "biber.user.blog.main.test"
MAPACHE = "mapache.user.blog.main.test"
WILDCARD = "*.user.blog.main.test"
ONION = "b5abfs7uwr23x6vbjxqjatyscpmkm6qkmkla7eyapdi4zpwtrz6o4nqd.onion"
ONION_PARENT = f"user.blog.{ONION}"
ONION_BLOG = f"blog.{ONION}"
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


def _as_declared(application_id, parent):
    return parent


def _on_tor(application_id, parent):
    return served_parent(parent, [ONION_BLOG], PRIMARY, ONION)


def _served(wildcard, known=("blog.main.test",), users=USERS):
    return served_domains(
        APPLICATIONS,
        users,
        [APP, OTHER, "web-app-absent"],
        wildcard_certificate=lambda app: wildcard,
        known_domains=list(known),
        parent_of=_as_declared,
    )


def _served_on_tor(wildcard, known):
    return served_domains(
        APPLICATIONS,
        USERS,
        [APP, OTHER],
        wildcard_certificate=lambda app: wildcard,
        known_domains=list(known),
        parent_of=_on_tor,
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
                "parents": [
                    {"application_id": APP, "role": "site-owner", "parent": PARENT}
                ],
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
            parent_of=_as_declared,
        )
        self.assertEqual([APPLICATIONS[APP]], seen)

    def test_each_declaration_asks_for_its_served_parent_once(self):
        asked = []

        def parent_of(application_id, parent):
            asked.append((application_id, parent))
            return parent

        served_domains(
            APPLICATIONS,
            USERS,
            [APP, OTHER],
            wildcard_certificate=lambda app: True,
            known_domains=[],
            parent_of=parent_of,
        )
        self.assertEqual([(APP, PARENT)], asked)

    def test_a_tor_only_application_serves_its_wildcard_below_the_onion_parent(self):
        result = _served_on_tor(True, known=(ONION_BLOG,))
        self.assertEqual(
            [
                {
                    "name": f"*.{ONION_PARENT}",
                    "application_id": APP,
                    "members": ["biber", "mapache"],
                    "hosts": [f"biber.{ONION_PARENT}", f"mapache.{ONION_PARENT}"],
                }
            ],
            result["entries"],
        )
        self.assertEqual(
            [{"application_id": APP, "role": "site-owner", "parent": ONION_PARENT}],
            result["parents"],
        )

    def test_a_tor_only_application_names_every_member_host_below_the_onion_parent(
        self,
    ):
        self.assertEqual(
            [f"biber.{ONION_PARENT}", f"mapache.{ONION_PARENT}"],
            [entry["name"] for entry in _served_on_tor(False, ())["entries"]],
        )

    def test_an_onion_member_host_that_repeats_a_known_domain_is_a_problem(self):
        result = _served_on_tor(False, known=(f"biber.{ONION_PARENT}",))
        self.assertEqual(
            [f"mapache.{ONION_PARENT}"],
            [entry["name"] for entry in result["entries"]],
        )
        self.assertEqual(1, len(result["problems"]))


class TestServedParent(unittest.TestCase):
    def test_a_tor_only_application_serves_the_onion_sibling_of_its_parent(self):
        self.assertEqual(
            ONION_PARENT, served_parent(PARENT, [ONION_BLOG], PRIMARY, ONION)
        )

    def test_an_application_with_a_clearnet_domain_keeps_its_parent(self):
        for app_domains in (["blog.main.test"], ["blog.main.test", ONION_BLOG]):
            with self.subTest(app_domains=app_domains):
                self.assertEqual(
                    PARENT, served_parent(PARENT, app_domains, PRIMARY, ONION)
                )

    def test_an_application_without_a_domain_keeps_its_parent(self):
        self.assertEqual(PARENT, served_parent(PARENT, [], PRIMARY, ONION))

    def test_a_parent_without_an_onion_sibling_stays_as_declared(self):
        for parent, node in (("user.example.org", ONION), (PARENT, "")):
            with self.subTest(parent=parent, node=node):
                self.assertEqual(
                    parent, served_parent(parent, [ONION_BLOG], PRIMARY, node)
                )

    def test_an_onion_parent_stays_on_tor(self):
        self.assertEqual(
            ONION_PARENT, served_parent(ONION_PARENT, [ONION_BLOG], PRIMARY, ONION)
        )


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
