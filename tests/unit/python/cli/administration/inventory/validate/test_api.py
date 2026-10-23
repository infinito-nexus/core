import shutil
import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.validate.api import (
    legacy_api_keys,
    validate_api_keys,
)

VAULTED_TOKEN = (
    "API:\n"
    "  cloudflare:\n"
    "    api_token: !vault |\n"
    "      $ANSIBLE_VAULT;1.1;AES256\n"
    "      3133\n"
)


class TestValidateApiKeys(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "host_vars").mkdir()
        (self.root / "group_vars").mkdir()

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, relative: str, text: str) -> None:
        (self.root / relative).write_text(text, encoding="utf-8")

    def test_cloudflare_without_a_token_is_reported(self):
        self.write("host_vars/echo.yml", "DNS_PROVIDER: cloudflare\n")
        errors = validate_api_keys(self.root)
        self.assertEqual(len(errors), 1)
        self.assertIn("API.cloudflare.api_token is empty", errors[0])

    def test_the_legacy_key_does_not_count_as_a_token(self):
        self.write(
            "host_vars/echo.yml",
            "DNS_PROVIDER: cloudflare\nCLOUDFLARE_API_TOKEN: abc\n",
        )
        self.assertEqual(len(validate_api_keys(self.root)), 1)

    def test_a_vaulted_token_in_the_host_file_passes(self):
        self.write("host_vars/echo.yml", "DNS_PROVIDER: cloudflare\n" + VAULTED_TOKEN)
        self.assertEqual(validate_api_keys(self.root), [])

    def test_a_token_in_group_vars_all_passes(self):
        self.write("host_vars/echo.yml", "DNS_PROVIDER: cloudflare\n")
        self.write("group_vars/all.yml", VAULTED_TOKEN)
        self.assertEqual(validate_api_keys(self.root), [])

    def test_a_host_api_mapping_replaces_the_group_one(self):
        self.write(
            "host_vars/echo.yml",
            "DNS_PROVIDER: cloudflare\nAPI:\n  telegram:\n    bot_token: x\n",
        )
        self.write("group_vars/all.yml", VAULTED_TOKEN)
        self.assertEqual(len(validate_api_keys(self.root)), 1)

    def test_another_dns_provider_needs_no_token(self):
        self.write("host_vars/echo.yml", "DNS_PROVIDER: localhost\n")
        self.assertEqual(validate_api_keys(self.root), [])


class TestLegacyApiKeys(unittest.TestCase):
    def test_a_moved_credential_names_its_api_path(self):
        self.assertEqual(
            legacy_api_keys(set())["CLOUDFLARE_API_TOKEN"], "API.cloudflare.api_token"
        )

    def test_a_name_core_still_declares_is_not_moved(self):
        self.assertNotIn("TELEGRAM_BOT_TOKEN", legacy_api_keys({"TELEGRAM_BOT_TOKEN"}))


if __name__ == "__main__":
    unittest.main()
