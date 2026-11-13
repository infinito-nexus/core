from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.ansible.roles.meta import test_env_forms as lint
from utils.roles.mapping import ROLE_FILE_META_FORMS

INCLUDE = (
    "- ansible.builtin.include_tasks: "
    "\"{{ lookup('path_absolute', 'tasks/utils/forms/env.yml') }}\"\n"
    "  vars:\n"
    "    forms_env_form: settings\n"
    '    forms_env_fields: "{{ X_SETTINGS }}"\n'
)
DOMAIN = 'source: a.b, mode: enforced, selector: "#d"'


def _role(root: Path, *fields: str) -> Path:
    role = root / "web-app-x"
    (role / "tasks").mkdir(parents=True)
    (role / "meta").mkdir()
    (role / "tasks" / "main.yml").write_text(INCLUDE, encoding="utf-8")
    (role / ROLE_FILE_META_FORMS).write_text(
        "settings:\n  path: /settings\n  fields:\n"
        + "".join(f"    {field}\n" for field in fields),
        encoding="utf-8",
    )
    return role


class TestEnvNames(unittest.TestCase):
    def _names(self, *fields: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            return lint.name_findings([_role(Path(tmp), *fields)])

    def _secrets(self, *fields: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            return lint.secret_findings([_role(Path(tmp), *fields)])

    def test_a_field_with_env_may_carry_any_key(self) -> None:
        self.assertEqual(
            [],
            self._names(
                f"webserverDomain: {{{DOMAIN}, env: FTLCONF_webserver_domain}}",
                f"mm_site: {{{DOMAIN}}}",
            ),
        )

    def test_a_key_without_env_stays_lower_snake_case(self) -> None:
        self.assertEqual(
            [
                (
                    "web-app-x.settings: dotenv_names: env form field"
                    " 'webserverDomain' is not lower snake_case"
                )
            ],
            self._names(f"webserverDomain: {{{DOMAIN}}}"),
        )

    def test_two_fields_naming_one_variable_are_refused(self) -> None:
        self.assertEqual(
            ["web-app-x.settings: dotenv_names: two env form fields name one variable"],
            self._names(f"site: {{{DOMAIN}, env: MM_SITE}}", f"mm_site: {{{DOMAIN}}}"),
        )

    def test_a_secret_class_env_name_is_refused(self) -> None:
        self.assertEqual(
            ["web-app-x.settings.domain: the env name is secret-class"],
            self._secrets(f"domain: {{{DOMAIN}, env: FTLCONF_webserver_api_password}}"),
        )

    def test_a_plain_env_name_passes_the_secret_check(self) -> None:
        self.assertEqual(
            [],
            self._secrets(f"domain: {{{DOMAIN}, env: FTLCONF_webserver_domain}}"),
        )


if __name__ == "__main__":
    unittest.main()
