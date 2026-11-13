from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

import plugins.lookup.form_values as module

APP = "web-app-demo"
FORMS = {
    "general": {
        "path": "/admin/settings",
        "fields": {
            "relay": {
                "source": "services.mail.relay",
                "mode": "enforced",
                "selector": "#relay",
            },
            "sender": {
                "source": "users.administrator.email",
                "mode": "seeded",
                "selector": "#sender",
            },
        },
    }
}
APPLICATION = {"forms": FORMS, "services": {"mail": {"relay": "relay.example.test"}}}
USERS = {"administrator": {"email": "admin@example.test"}}


class TestFormValues(unittest.TestCase):
    def _run(self, terms: list, application: dict = APPLICATION, **kwargs):
        spots = {"applications": application, "users": USERS}

        def get(name, **_kwargs):
            spot = mock.MagicMock()
            spot.run.return_value = [spots[name]]
            return spot

        with mock.patch.object(module.lookup_loader, "get", side_effect=get):
            return module.LookupModule().run(terms, variables={}, **kwargs)

    def test_the_form_resolves_to_its_sources(self):
        self.assertEqual(
            [{"relay": "relay.example.test", "sender": "admin@example.test"}],
            self._run([APP, "general"]),
        )

    def test_a_mode_keeps_only_its_fields(self):
        self.assertEqual(
            [{"sender": "admin@example.test"}],
            self._run([APP, "general"], mode="seeded"),
        )

    def test_an_unknown_mode_fails(self):
        with self.assertRaises(AnsibleError):
            self._run([APP, "general"], mode="locked")

    def test_an_undeclared_form_fails(self):
        with self.assertRaises(AnsibleError) as caught:
            self._run([APP, "mail"])
        self.assertIn("declares no form 'mail'", str(caught.exception))

    def test_a_role_without_forms_fails(self):
        with self.assertRaises(AnsibleError):
            self._run([APP, "general"], application={"services": {}})

    def test_a_source_that_names_nothing_fails_without_repeating_it(self):
        broken = {"forms": FORMS, "services": {"mail": {}}}
        with self.assertRaises(AnsibleError) as caught:
            self._run([APP, "general"], application=broken)
        self.assertNotIn("services.mail.relay", str(caught.exception))

    def test_the_terms_are_the_role_and_the_form(self):
        with self.assertRaises(AnsibleError):
            self._run([APP])


if __name__ == "__main__":
    unittest.main()
