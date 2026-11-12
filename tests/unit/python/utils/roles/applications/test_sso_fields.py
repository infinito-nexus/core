from __future__ import annotations

import unittest

from utils.roles.applications import forms, sso_fields
from utils.roles.applications.converge import values

FORMS = {
    "general": {
        "path": "/admin/settings",
        "fields": {
            "title": {
                "source": "design.label",
                "mode": "enforced",
                "selector": "#title",
                "type": "text",
            }
        },
    },
    "profile": {
        "path": "/profile",
        "fields": {
            "email": {
                "source": "sso.email",
                "mode": "enforced",
                "selector": "#email[data-sso]",
            },
            "name": {
                "source": "sso.name",
                "mode": "enforced",
                "selector": "#name[data-sso]",
            },
        },
    },
}
APPLICATION = {"design": {"label": "Infinito.Nexus"}}
USERS: dict = {}


class TestClaims(unittest.TestCase):
    def test_the_claims_come_from_the_oidc_attributes_of_the_group_vars(self):
        self.assertTrue(
            {"email", "name", "preferred_username", "locale"} <= sso_fields.claims()
        )
        self.assertNotIn("EMAIL", sso_fields.claims())


class TestErrors(unittest.TestCase):
    def test_a_known_claim_on_an_enforced_field_passes(self):
        self.assertEqual([], sso_fields.errors("web-app-demo", FORMS))

    def test_an_unknown_or_nested_claim_fails_without_repeating_it(self):
        for source in ("sso.shoe_size", "sso.email.domain", "sso"):
            with self.subTest(source=source):
                broken = {
                    "profile": {
                        "path": "/profile",
                        "fields": {
                            "email": {
                                **FORMS["profile"]["fields"]["email"],
                                "source": source,
                            }
                        },
                    }
                }
                found = sso_fields.errors("web-app-demo", broken)
                self.assertEqual(1, len(found))
                self.assertIn("must be sso.<claim>", found[0])
                self.assertNotIn(source + " ", found[0])

    def test_a_seeded_or_guarded_sso_field_fails(self):
        field = FORMS["profile"]["fields"]["email"]
        for spec, message in (
            ({**field, "mode": "seeded"}, "mode must be enforced"),
            ({**field, "when": "design.label"}, "takes no `when`"),
        ):
            with self.subTest(message=message):
                broken = {"profile": {"path": "/profile", "fields": {"email": spec}}}
                self.assertIn(
                    message, "\n".join(sso_fields.errors("web-app-demo", broken))
                )

    def test_a_form_of_sso_fields_takes_no_record(self):
        record = {"selector": "#username", "source": "design.label"}
        guarded = {
            **FORMS,
            "general": {**FORMS["general"], "record": record},
            "profile": {**FORMS["profile"], "record": record},
        }
        self.assertEqual(
            [
                "web-app-demo: profile.email takes no `record`; the selector's marker decides",
                "web-app-demo: profile.name takes no `record`; the selector's marker decides",
            ],
            sso_fields.errors("web-app-demo", guarded),
        )


class TestSelectors(unittest.TestCase):
    def test_only_the_sso_fields_reach_the_server_guards(self):
        self.assertEqual(
            {"email": "#email[data-sso]", "name": "#name[data-sso]"},
            sso_fields.selectors(FORMS),
        )

    def test_a_form_of_sso_fields_only_is_recognised(self):
        self.assertTrue(sso_fields.only_sso(FORMS["profile"]))
        self.assertFalse(sso_fields.only_sso(FORMS["general"]))
        self.assertFalse(sso_fields.only_sso({"path": "/x", "fields": {}}))


class TestTheFormsMachinery(unittest.TestCase):
    def test_an_sso_source_has_no_deploy_time_value(self):
        with self.assertRaises(forms.SourceError):
            forms.resolve("sso.email", APPLICATION, USERS)

    def test_the_converge_leaves_the_sso_fields_out(self):
        self.assertEqual({}, values("profile", FORMS, APPLICATION, USERS))
        self.assertEqual(
            {"title": "Infinito.Nexus"}, values("general", FORMS, APPLICATION, USERS)
        )

    def test_the_source_check_leaves_the_sso_fields_to_their_own_check(self):
        self.assertEqual(
            [], forms.source_errors("web-app-demo", FORMS, APPLICATION, USERS, {})
        )

    def test_the_sso_fields_of_a_page_lock_as_one_profile_entry_first(self):
        entries = forms.locks("web-app-demo", FORMS, APPLICATION, USERS, {})

        self.assertEqual(
            [
                {
                    "page": "/profile",
                    "selector": "#email[data-sso],#name[data-sso]",
                    "label": None,
                    "path": None,
                    "secret": False,
                },
                {
                    "page": "/admin/settings",
                    "selector": "#title",
                    "label": "title",
                    "path": "applications.web-app-demo.design.label",
                    "secret": False,
                },
            ],
            entries,
        )


if __name__ == "__main__":
    unittest.main()
