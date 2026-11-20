from __future__ import annotations

import unittest

from utils.roles.applications.converge import values
from utils.roles.applications.forms import SourceError

FORMS = {
    "general": {
        "path": "/admin/settings",
        "fields": {
            "title": {
                "source": "design.title",
                "when": "design.enabled",
                "mode": "enforced",
                "selector": "#title",
            },
            "sender": {
                "source": "users.administrator.email",
                "mode": "seeded",
                "selector": "#sender",
            },
            "relay": {
                "source": "mail.relay",
                "mode": "enforced",
                "selector": "#relay",
            },
        },
    },
    "mail": {
        "path": "/admin/mail",
        "fields": {
            "port": {"source": "mail.port", "mode": "enforced", "selector": "#port"},
        },
    },
}
APPLICATION = {
    "design": {"enabled": True, "title": "Fixture"},
    "mail": {"relay": "relay.example.test", "port": 587},
}
USERS = {"administrator": {"email": "admin@example.test"}}
OPTIONAL = {
    "general": {
        "path": "/admin/settings",
        "fields": {"title": {**FORMS["general"]["fields"]["title"], "optional": True}},
    }
}


class TestValues(unittest.TestCase):
    def test_each_field_of_the_form_gets_its_source_in_yaml_order(self):
        result = values("general", FORMS, APPLICATION, USERS)

        self.assertEqual(
            {
                "title": "Fixture",
                "sender": "admin@example.test",
                "relay": "relay.example.test",
            },
            result,
        )
        self.assertEqual(["title", "sender", "relay"], list(result))

    def test_a_field_of_another_form_stays_out(self):
        self.assertEqual({"port": 587}, values("mail", FORMS, APPLICATION, USERS))

    def test_a_field_whose_when_fails_stays_out(self):
        design_off = {**APPLICATION, "design": {"enabled": False, "title": "Fixture"}}

        self.assertNotIn("title", values("general", FORMS, design_off, USERS))

    def test_a_mode_keeps_only_its_fields(self):
        self.assertEqual(
            ["title", "relay"],
            list(values("general", FORMS, APPLICATION, USERS, "enforced")),
        )
        self.assertEqual(
            ["sender"], list(values("general", FORMS, APPLICATION, USERS, "seeded"))
        )

    def test_an_unknown_form_converges_nothing(self):
        self.assertEqual({}, values("absent", FORMS, APPLICATION, USERS))

    def test_a_source_that_names_nothing_fails_without_repeating_it(self):
        broken = {**APPLICATION, "mail": {"port": 587}}

        with self.assertRaises(SourceError) as caught:
            values("general", FORMS, broken, USERS)

        self.assertNotIn("mail.relay", str(caught.exception))

    def test_a_source_that_stayed_template_text_fails_without_repeating_it(self):
        for unrendered in (
            "{{ lookup('redirect_uris') }}",
            ["https://a.example.test/*", "{{ OIDC.CLIENT.ID }}"],
            {"nested": "{% if relay %}x{% endif %}"},
        ):
            with self.subTest(unrendered=unrendered):
                broken = {**APPLICATION, "mail": {"relay": unrendered, "port": 587}}

                with self.assertRaises(SourceError) as caught:
                    values("general", FORMS, broken, USERS)

                self.assertIn("relay", str(caught.exception))
                self.assertNotIn("mail.relay", str(caught.exception))

    def test_a_when_that_stayed_template_text_names_its_field_but_no_value(self):
        unrendered = "{{ lookup('objstore', 'web-app-odoo', 'enabled') | bool }}"
        broken = {**APPLICATION, "design": {"enabled": unrendered, "title": "x"}}

        with self.assertRaises(SourceError) as caught:
            values("general", FORMS, broken, USERS)

        self.assertIn("general.title.when design.enabled", str(caught.exception))
        self.assertNotIn("lookup", str(caught.exception))

    def test_an_optional_field_whose_source_is_false_stays_out(self):
        for title, expected in (("Fixture", {"title": "Fixture"}), (False, {})):
            with self.subTest(title=title):
                application = {
                    **APPLICATION,
                    "design": {"enabled": True, "title": title},
                }
                self.assertEqual(
                    expected, values("general", OPTIONAL, application, USERS)
                )

    def test_an_optional_field_reads_its_source_only_while_its_when_holds(self):
        design_off = {"design": {"enabled": False}}

        self.assertEqual({}, values("general", OPTIONAL, design_off, USERS))

    def test_a_false_source_converges_unless_the_field_is_optional(self):
        application = {**APPLICATION, "design": {"enabled": True, "title": False}}

        self.assertIs(False, values("general", FORMS, application, USERS)["title"])

    def test_the_source_of_a_skipped_field_is_never_read(self):
        design_off = {"design": {"enabled": False}, "mail": APPLICATION["mail"]}

        self.assertEqual(
            ["sender", "relay"], list(values("general", FORMS, design_off, USERS))
        )


REGISTRATION = {
    "general": {
        "path": "/admin/settings",
        "fields": {
            "open": {
                "source": "login.registration",
                "when": "!multisite.enabled",
                "mode": "enforced",
                "selector": "#open",
                "map": {True: "1", False: "0"},
            },
        },
    },
    "network": {
        "path": "/admin/network",
        "fields": {
            "registration": {
                "source": "login.registration",
                "when": "multisite.enabled",
                "mode": "enforced",
                "selector": "#registration",
                "map": {True: "user", False: "none"},
            },
        },
    },
}


def _site(*, registration: object, multisite: bool) -> dict:
    return {
        "login": {"registration": registration},
        "multisite": {"enabled": multisite},
    }


class TestMapAndNegatedWhen(unittest.TestCase):
    def test_the_map_turns_the_source_value_into_the_stored_value(self):
        for registration, stored in ((True, "1"), (False, "0"), ("True", "1")):
            with self.subTest(registration=registration):
                site = _site(registration=registration, multisite=False)
                self.assertEqual(
                    {"open": stored}, values("general", REGISTRATION, site, USERS)
                )

    def test_a_negated_when_applies_the_field_while_its_path_is_false(self):
        network = _site(registration=True, multisite=True)

        self.assertEqual({}, values("general", REGISTRATION, network, USERS))
        self.assertEqual(
            {"registration": "user"}, values("network", REGISTRATION, network, USERS)
        )
        self.assertEqual(
            {},
            values(
                "network",
                REGISTRATION,
                _site(registration=True, multisite=False),
                USERS,
            ),
        )

    def test_a_value_the_map_does_not_hold_fails_without_repeating_it(self):
        site = _site(registration="sometimes", multisite=False)

        with self.assertRaises(SourceError) as caught:
            values("general", REGISTRATION, site, USERS)

        self.assertNotIn("sometimes", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
