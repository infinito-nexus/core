"""Unit tests for plugins/lookup/field_locks.py.

The ``applications`` and ``users`` SPOT lookups are stubbed; the role's
``meta/secrets.yml`` is read from a temporary roles tree.
"""

from __future__ import annotations

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


def _application(*, profile: bool, managed: bool) -> dict:
    application: dict = {"services": {"sso": {"enabled": True}}}
    if profile:
        application["services"]["sso"]["profile"] = {
            "locked": PROFILE,
            "languages": ["en", "de"],
        }
    if managed:
        application["forms"] = FORMS
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

    def test_the_profile_lock_comes_first_as_one_entry_without_unlock(self):
        entries = self._run(_application(profile=True, managed=True))["locks"]

        self.assertEqual(
            {
                "page": None,
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
            {"locks": [], "languages": None},
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

    def test_one_application_id_is_required(self):
        with self.assertRaises(AnsibleError):
            module.LookupModule().run([], variables={})


if __name__ == "__main__":
    unittest.main()
