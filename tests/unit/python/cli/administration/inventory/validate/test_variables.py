import shutil
import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.validate.variables import (
    declared_variables,
    read_variables,
    validate_inventory_variables,
)

KNOWN = {"DOMAIN_PRIMARY", "applications"}
MOVED = {"CLOUDFLARE_API_TOKEN": "API.cloudflare.api_token"}


class TestValidateInventoryVariables(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "host_vars").mkdir()
        (self.root / "group_vars").mkdir()

    def tearDown(self):
        shutil.rmtree(self.root)

    def errors(self, relative: str, text: str) -> list[str]:
        (self.root / relative).write_text(text, encoding="utf-8")
        return validate_inventory_variables(self.root, KNOWN, MOVED)

    def test_a_read_variable_passes(self):
        text = "DOMAIN_PRIMARY: x\napplications: {}\n"
        self.assertEqual(self.errors("host_vars/echo.yml", text), [])

    def test_an_unread_constant_fails(self):
        errors = self.errors("host_vars/echo.yml", "SYSTEM_EMAIL: x\n")
        self.assertEqual(len(errors), 1)
        self.assertIn("'SYSTEM_EMAIL' is not read by the deploy", errors[0])

    def test_a_moved_credential_names_its_new_path(self):
        errors = self.errors("host_vars/echo.yml", "CLOUDFLARE_API_TOKEN: x\n")
        self.assertIn("move its value to API.cloudflare.api_token", errors[0])

    def test_ansible_variables_pass(self):
        text = "ansible_host: x\nansible_become_password: y\n"
        self.assertEqual(self.errors("host_vars/echo.yml", text), [])

    def test_group_vars_are_checked_too(self):
        self.assertEqual(len(self.errors("group_vars/all.yml", "LEGACY: x\n")), 1)

    def test_a_host_vars_directory_is_checked(self):
        (self.root / "host_vars" / "echo").mkdir()
        self.assertEqual(len(self.errors("host_vars/echo/main.yml", "LEGACY: x\n")), 1)

    def test_a_marker_on_the_key_line_allows_it(self):
        text = "OLD_DOMAIN: x # nocheck: inventory-variable\n"
        self.assertEqual(self.errors("host_vars/echo.yml", text), [])

    def test_a_marker_above_the_key_allows_it(self):
        text = "# nocheck: inventory-variable\nOLD_DOMAIN: x\n"
        self.assertEqual(self.errors("host_vars/echo.yml", text), [])

    def test_a_vaulted_unread_value_fails(self):
        text = "LEGACY_TOKEN: !vault |\n  $ANSIBLE_VAULT;1.1;AES256\n  3133\n"
        self.assertEqual(len(self.errors("host_vars/echo.yml", text)), 1)


class TestReadVariables(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.read = read_variables()

    def test_declarations_count(self):
        self.assertLessEqual(declared_variables(), self.read)
        self.assertIn("TELEGRAM_BOT_TOKEN", self.read)

    def test_guarded_overrides_count(self):
        self.assertIn("OIDC_OVERRIDE", self.read)

    def test_plugin_reads_count(self):
        self.assertIn("networks", self.read)
        self.assertIn("SYSTEM_EMAIL_DOMAIN", self.read)

    def test_the_email_lookup_names_count(self):
        self.assertIn("SYSTEM_EMAIL_HOST", self.read)
        self.assertIn("SYSTEM_EMAIL_EXTERNAL", self.read)

    def test_retired_names_do_not_count(self):
        for name in ("CLOUDFLARE_API_TOKEN", "SYSTEM_EMAIL", "internet_interfaces"):
            with self.subTest(name=name):
                self.assertNotIn(name, self.read)


if __name__ == "__main__":
    unittest.main()
