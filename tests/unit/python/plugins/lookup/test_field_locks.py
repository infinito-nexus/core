"""Unit tests for plugins/lookup/field_locks.py.

The ``applications`` and ``users`` SPOT lookups are stubbed; the role's
``meta/secrets.yml`` is read from a temporary roles tree.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from ansible.errors import AnsibleError

import plugins.lookup.field_locks as module
from utils.roles.mapping import ROLE_FILE_META_SECRETS

APP = "web-app-demo"
PROFILE = {"name": "#name[data-locked]", "email": "#email[data-locked]"}
FORMS = {
    "general": {
        "path": "/admin/settings",
        "fields": {
            "relay": {
                "source": "services.mail.relay",
                "mode": "enforced",
                "selector": "#relay",
                "type": "text",
            },
            "sender": {
                "source": "users.administrator.email",
                "mode": "seeded",
                "selector": "#sender",
            },
        },
    }
}


PROFILE_FORM = {
    "profile": {
        "path": "/profile",
        "fields": {
            field: {"source": f"sso.{field}", "mode": "enforced", "selector": selector}
            for field, selector in PROFILE.items()
        },
    }
}


def _application(*, profile: bool, managed: bool) -> dict:
    application: dict = {"services": {"sso": {"enabled": True}}}
    forms: dict = {}
    if profile:
        application["services"]["sso"]["profile"] = {"languages": ["en", "de"]}
        forms.update(PROFILE_FORM)
    if managed:
        forms.update(FORMS)
    if forms:
        application["forms"] = forms
    return application


class TestFieldLocks(unittest.TestCase):
    def _run(self, application: dict, secrets: str = "") -> dict:
        spots = {"applications": application, "users": {"administrator": {}}}

        def get(name, **_kwargs):
            spot = mock.MagicMock()
            spot.run.return_value = [spots[name]]
            return spot

        with tempfile.TemporaryDirectory() as tmp:
            role = Path(tmp) / APP
            (role / "meta").mkdir(parents=True)
            if secrets:
                (role / ROLE_FILE_META_SECRETS).write_text(secrets, encoding="utf-8")
            with (
                mock.patch.object(module, "ROLES_DIR", Path(tmp)),
                mock.patch.object(module.lookup_loader, "get", side_effect=get),
            ):
                return module.LookupModule().run([APP], variables={})[0]

    def test_the_sso_fields_lock_as_one_profile_entry_without_unlock(self):
        entries = self._run(_application(profile=True, managed=True))["locks"]

        self.assertEqual(
            {
                "page": "/profile",
                "selector": ",".join(PROFILE.values()),
                "label": None,
                "path": None,
                "secret": False,
            },
            entries[0],
        )
        self.assertEqual(
            ["#relay"], [entry["selector"] for entry in entries if entry["path"]]
        )

    def test_the_server_guards_get_each_sso_field_and_its_selector(self):
        self.assertEqual(
            PROFILE, self._run(_application(profile=True, managed=True))["profile"]
        )
        self.assertEqual(
            {}, self._run(_application(profile=False, managed=True))["profile"]
        )

    def test_a_role_with_forms_only_locks_its_enforced_fields(self):
        entries = self._run(_application(profile=False, managed=True))["locks"]

        self.assertEqual(
            [
                {
                    "page": "/admin/settings",
                    "selector": "#relay",
                    "label": "relay",
                    "path": f"applications.{APP}.services.mail.relay",
                    "secret": False,
                }
            ],
            entries,
        )

    def test_a_role_with_neither_locks_nothing(self):
        self.assertEqual(
            {"locks": [], "languages": None, "profile": {}},
            self._run(_application(profile=False, managed=False)),
        )

    def test_the_profile_languages_cut_the_catalogue(self):
        self.assertEqual(
            ["en", "de"],
            self._run(_application(profile=True, managed=False))["languages"],
        )

    def test_a_credential_of_the_secrets_file_hides_the_value(self):
        entries = self._run(
            _application(profile=False, managed=True),
            "credentials:\n  relay:\n    algorithm: alphanumeric\n",
        )["locks"]

        self.assertTrue(entries[0]["secret"])

    def test_a_when_that_stayed_template_text_fails_naming_the_application(self):
        application = copy.deepcopy(_application(profile=False, managed=True))
        application["services"]["mail"] = {
            "relay": "relay.example.test",
            "enabled": "{{ lookup('email', APP) }}",
        }
        application["forms"]["general"]["fields"]["relay"]["when"] = (
            "services.mail.enabled"
        )

        with self.assertRaises(AnsibleError) as caught:
            self._run(application)

        message = str(caught.exception)
        self.assertIn(f"field_locks: {APP}", message)
        self.assertIn("general.relay.when services.mail.enabled", message)
        self.assertNotIn("lookup", message)

    def test_one_application_id_is_required(self):
        with self.assertRaises(AnsibleError):
            module.LookupModule().run([], variables={})


if __name__ == "__main__":
    unittest.main()
