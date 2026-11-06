"""Negative controls for the managed-field lint of ``meta/forms.yml``."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.lint.ansible.roles.meta import test_forms as lint
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_META_SECRETS

ROLE = "web-app-fixture"
DEFAULTS = {ROLE: {"design": {"label": "Fixture"}}}
USERS = {"administrator": {"email": "admin@example.com"}}
SECRETS = """
credentials:
  smtp_password:
    algorithm: alphanumeric
    length: 32
"""
VALID = """
general:
  path: /admin/settings
  fields:
    title:
      source: design.label
      mode: enforced
      selector: "#title"
    email:
      source: users.administrator.email
      mode: seeded
      selector: "#email"
    smtp_password:
      source: secrets.credentials.smtp_password
      mode: enforced
      selector: "#smtp_password"
"""


class TestFormsLint(unittest.TestCase):
    def _findings(self, forms_yml: str) -> list[str]:
        return self._findings_with(forms_yml, DEFAULTS, USERS)

    @staticmethod
    def _findings_with(forms_yml: str, defaults: dict, users: dict) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            role = Path(tmp) / ROLE
            for name, content in (
                (ROLE_FILE_META_FORMS, forms_yml),
                (ROLE_FILE_META_SECRETS, SECRETS),
            ):
                path = role / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(content), encoding="utf-8")
            return lint.findings([role], defaults, users)

    def test_a_valid_file_passes(self) -> None:
        self.assertEqual([], self._findings(VALID))

    def test_a_field_without_mode_fails(self) -> None:
        broken = VALID.replace("      mode: seeded\n", "")
        self.assertEqual(
            [f"{ROLE}: general.fields.email lacks `mode`"], self._findings(broken)
        )

    def test_a_field_without_source_or_selector_fails(self) -> None:
        broken = VALID.replace("      source: design.label\n", "").replace(
            '      selector: "#email"\n', ""
        )
        self.assertEqual(
            [
                f"{ROLE}: general.fields.title lacks `source`",
                f"{ROLE}: general.fields.email lacks `selector`",
            ],
            self._findings(broken),
        )

    def test_an_unknown_mode_fails(self) -> None:
        findings = self._findings(VALID.replace("mode: seeded", "mode: once"))
        self.assertEqual(1, len(findings))
        self.assertIn("mode 'once' is not one of", findings[0])

    def test_a_source_that_does_not_resolve_fails(self) -> None:
        broken = VALID.replace("source: design.label", "source: design.title")
        self.assertEqual(
            [f"{ROLE}: general.title.source names nothing in the inventory"],
            self._findings(broken),
        )

    def test_a_dotted_secret_in_when_is_never_echoed(self) -> None:
        secret = "SG.SYNTH-SECRET-1.abcdef0123"
        broken = VALID.replace(
            '      selector: "#title"\n',
            f'      selector: "#title"\n      when: {secret}\n',
        )
        findings = self._findings(broken)
        self.assertEqual(
            [f"{ROLE}: general.title.when names nothing in the inventory"], findings
        )
        self.assertNotIn("SYNTH-SECRET-1", findings[0])

    def test_a_template_in_a_forms_string_fails(self) -> None:
        broken = VALID.replace('selector: "#title"', 'selector: "#{{ title_id }}"')
        self.assertEqual(
            [
                (
                    f"{ROLE}: general.fields.title.selector must hold no template;"
                    f" {ROLE_FILE_META_FORMS} is never rendered"
                )
            ],
            self._findings(broken),
        )

    def test_an_undeclared_credential_fails(self) -> None:
        broken = VALID.replace(
            "secrets.credentials.smtp_password", "secrets.credentials.imap_password"
        )
        self.assertEqual(
            [f"{ROLE}: general.smtp_password.source names nothing in the inventory"],
            self._findings(broken),
        )

    def test_an_unknown_user_fails(self) -> None:
        broken = VALID.replace("users.administrator.email", "users.biber.email")
        self.assertEqual(
            [f"{ROLE}: general.email.source names nothing in the inventory"],
            self._findings(broken),
        )

    def test_a_user_source_other_than_a_plain_attribute_fails(self) -> None:
        role_users = {"administrator": {"email": "a@x", "password": "pw", "tokens": {}}}
        defaults = {ROLE: {**DEFAULTS[ROLE], "users": role_users}}
        for source in ("users.administrator", "users.administrator.tokens"):
            with self.subTest(source=source):
                broken = VALID.replace("users.administrator.email", source)
                self.assertEqual(
                    [
                        (
                            f"{ROLE}: general.email.source must be "
                            "users.<key>.<attr> with an attr other than ['tokens']"
                        )
                    ],
                    self._findings_with(broken, defaults, {**USERS, **role_users}),
                )

    def test_a_user_password_source_passes(self) -> None:
        users = {"administrator": {"email": "a@x", "password": "SYNTH-PW"}}
        allowed = VALID.replace(
            "users.administrator.email", "users.administrator.password"
        )
        self.assertEqual([], self._findings_with(allowed, DEFAULTS, users))


if __name__ == "__main__":
    unittest.main()
