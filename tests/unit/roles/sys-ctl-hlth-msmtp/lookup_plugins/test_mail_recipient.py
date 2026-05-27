from __future__ import annotations

import importlib.util
import sys
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class _DummyTemplar:
    def __init__(self, available_variables: dict | None = None):
        self.available_variables = available_variables or {}


class MailRecipientLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module(
            "roles/sys-ctl-hlth-msmtp/lookup_plugins/mail_recipient.py",
            "mail_recipient",
        )

    def _make_lookup(self):
        lm = self.module.LookupModule()
        lm._templar = _DummyTemplar()
        return lm

    def _stub_email(self, external):
        return patch.object(
            self.module.EmailLookup,
            "run",
            return_value=[{"external": external, "timeout": "30"}],
        )

    def _stub_users(self, email_value):
        return patch.object(
            self.module.UsersLookup,
            "run",
            return_value=[{"email": email_value, "username": "administrator"}],
        )

    def test_external_true_returns_admin_email(self):
        lookup = self._make_lookup()
        with self._stub_email(True), self._stub_users("admin@example.com"):
            self.assertEqual(lookup.run([])[0], "admin@example.com")

    def test_external_string_true_returns_admin_email(self):
        lookup = self._make_lookup()
        with self._stub_email("true"), self._stub_users("admin@example.com"):
            self.assertEqual(lookup.run([])[0], "admin@example.com")

    def test_external_string_false_falls_into_local_branch(self):
        lookup = self._make_lookup()
        with (
            self._stub_email("false"),
            patch.object(
                self.module.pwd, "getpwnam", side_effect=KeyError("administrator")
            ),
        ):
            self.assertEqual(lookup.run([])[0], "root")

    def test_local_with_administrator_user_present(self):
        lookup = self._make_lookup()
        with (
            self._stub_email(False),
            patch.object(self.module.pwd, "getpwnam", return_value=object()),
        ):
            self.assertEqual(lookup.run([])[0], "administrator")

    def test_local_without_administrator_user_falls_back_to_root(self):
        lookup = self._make_lookup()
        with (
            self._stub_email(False),
            patch.object(
                self.module.pwd, "getpwnam", side_effect=KeyError("administrator")
            ),
        ):
            self.assertEqual(lookup.run([])[0], "root")

    def test_external_true_missing_email_falls_back_to_root(self):
        lookup = self._make_lookup()
        with (
            self._stub_email(True),
            patch.object(
                self.module.UsersLookup,
                "run",
                return_value=[{"username": "administrator"}],
            ),
        ):
            self.assertEqual(lookup.run([])[0], "root")


if __name__ == "__main__":
    unittest.main()
