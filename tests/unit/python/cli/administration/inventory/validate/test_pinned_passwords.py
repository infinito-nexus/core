"""Unit tests for ``cli.administration.inventory.validate.pinned_passwords``."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cli.administration.inventory.validate.pinned_passwords import (
    validate_pinned_passwords,
)
from utils.roles.mapping import ROLE_FILE_META_USERS

VAULTED_PIN = (
    "users:\n"
    "  platform_administrator:\n"
    "    password: !vault |\n"
    "      $ANSIBLE_VAULT;1.1;AES256\n"
    "      61626364\n"
)


class TestValidatePinnedPasswords(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.roles_dir = root / "roles"
        self.inv_dir = root / "inventory"
        self.write_role("web-app-a", "platform_administrator:\n  accounts: []\n")
        self.write_role("web-app-b", "bob:\n  accounts: []\n")
        self.write("devices.yml", self.devices({"web-app-a": ["echoserver"]}))
        self.write("host_vars/echoserver.yml", "ansible_connection: ssh\n")

    def write_role(self, application_id: str, users: str) -> None:
        path = self.roles_dir / application_id / ROLE_FILE_META_USERS
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(users, encoding="utf-8")

    def write(self, relative: str, text: str) -> None:
        path = self.inv_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def devices(groups: dict[str, list[str]]) -> str:
        lines = ["all:", "  children:"]
        for group, hosts in groups.items():
            lines += [f"    {group}:", "      hosts:"]
            lines += [f"        {host}: {{}}" for host in hosts]
        return "\n".join(lines) + "\n"

    def validate(self) -> list[str]:
        return validate_pinned_passwords(self.inv_dir, self.roles_dir)

    def test_a_host_missing_a_required_password_fails(self):
        expected = (
            "echoserver: no pinned password for users.platform_administrator; "
            "each falls back to a generated password that changes on every "
            "read. Pin them with: infinito administration inventory provision "
            f"{self.inv_dir} --host echoserver --include web-app-a "
            f"--inventory-file <scratch copy of {self.inv_dir / 'devices.yml'}> "
            "--vault-password-file <vault password file>"
        )
        self.assertEqual(self.validate(), [expected])

    def test_a_vaulted_password_in_host_vars_passes(self):
        self.write("host_vars/echoserver.yml", VAULTED_PIN)
        self.assertEqual(self.validate(), [])

    def test_a_user_only_a_role_the_host_does_not_run_needs_is_not_demanded(self):
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertNotIn("users.bob", errors[0])

    def test_a_user_of_every_group_of_the_host_is_demanded(self):
        self.write(
            "devices.yml",
            self.devices({"web-app-a": ["echoserver"], "web-app-b": ["echoserver"]}),
        )
        self.write("host_vars/echoserver.yml", VAULTED_PIN)
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("no pinned password for users.bob;", errors[0])
        self.assertIn("--include web-app-a,web-app-b ", errors[0])

    def test_a_password_pinned_in_group_vars_all_counts(self):
        self.write("group_vars/all.yml", VAULTED_PIN)
        self.assertEqual(self.validate(), [])

    def test_a_password_pinned_in_the_group_vars_of_a_group_counts(self):
        self.write("group_vars/web-app-a/users.yml", VAULTED_PIN)
        self.assertEqual(self.validate(), [])

    def test_users_in_host_vars_replace_the_users_of_group_vars(self):
        self.write("group_vars/all.yml", VAULTED_PIN)
        self.write("host_vars/echoserver.yml", "users:\n  bob:\n    password: x\n")
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("users.platform_administrator;", errors[0])

    def test_an_empty_password_is_not_a_pin(self):
        self.write(
            "host_vars/echoserver.yml",
            "users:\n  platform_administrator:\n    password: ''\n",
        )
        self.assertEqual(len(self.validate()), 1)

    def test_each_host_is_judged_on_its_own_variables(self):
        self.write(
            "devices.yml", self.devices({"web-app-a": ["echoserver", "galaxyserver"]})
        )
        self.write("host_vars/echoserver.yml", VAULTED_PIN)
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("galaxyserver: "))

    def test_a_host_in_no_group_still_needs_the_catalogue_bots(self):
        self.write_role("web-app-c", "relay:\n  roles: [bot]\n  accounts: []\n")
        self.write("devices.yml", "all:\n  hosts:\n    lonely: {}\n")
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("lonely: no pinned password for users.relay;", errors[0])
        self.assertIn("--include <application ids> ", errors[0])

    def test_a_directory_without_an_inventory_file_has_nothing_to_check(self):
        (self.inv_dir / "devices.yml").unlink()
        self.assertEqual(self.validate(), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
