"""Unit tests for utils/roles/applications/converge.py."""

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

    def test_the_source_of_a_skipped_field_is_never_read(self):
        design_off = {"design": {"enabled": False}, "mail": APPLICATION["mail"]}

        self.assertEqual(
            ["sender", "relay"], list(values("general", FORMS, design_off, USERS))
        )


if __name__ == "__main__":
    unittest.main()
