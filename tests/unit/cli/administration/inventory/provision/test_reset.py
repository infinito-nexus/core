import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ruamel.yaml import YAML

from cli.administration.inventory.provision.reset import reset_credentials
from cli.administration.inventory.provision.ruamel_io import load_document
from utils.roles.mapping import ROLE_FILE_META_USERS

MODULE = "cli.administration.inventory.provision.reset"

HOST_VARS = """\
---
# This comment must survive the rotation.
TLS_ENABLED: true

ansible_become_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  6265636f6d65

applications:
  web-app-a:
    credentials:
      api_key: !vault |
        $ANSIBLE_VAULT;1.1;AES256
        6170695f6b6579
      smtp_password: ''
      recaptcha:
        secret: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          7365637265740a
    features:
      matomo: true
  web-app-keycloak:
    credentials:
      database_password: !vault |
        $ANSIBLE_VAULT;1.1;AES256
        6462706173730a

users:
  administrator:
    password: !vault |
      $ANSIBLE_VAULT;1.1;AES256
      61646d696e0a
  newsletter:
    password: !vault |
      $ANSIBLE_VAULT;1.1;AES256
      6e6577730a
  biber:
    password: VeryUnsecurePassword!1
"""

DECLARED_USERS = """\
---
administrator:
  uid: 1001
newsletter:
  uid: 1002
"""


class TestResetCredentials(unittest.TestCase):
    def setUp(self):
        self.workdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.workdir, ignore_errors=True)

        self.roles_dir = self.workdir / "roles"
        for application_id in ("web-app-a", "web-app-keycloak"):
            users_file = self.roles_dir / application_id / ROLE_FILE_META_USERS
            users_file.parent.mkdir(parents=True, exist_ok=True)
            users_file.write_text(DECLARED_USERS, encoding="utf-8")

        self.host_vars_file = self.workdir / "host_vars" / "localhost.yml"
        self.host_vars_file.parent.mkdir(parents=True, exist_ok=True)
        self.host_vars_file.write_text(HOST_VARS, encoding="utf-8")

    def _reset(self, **overrides):
        arguments = {
            "application_ids": ["web-app-a", "web-app-keycloak"],
            "roles_dir": self.roles_dir,
            "host_vars_file": self.host_vars_file,
            "vault_password_file": self.workdir / ".password",
            "project_root": self.workdir,
            "env": None,
            "schema": True,
            "users": True,
            "exclude": {"administrator"},
        }
        arguments.update(overrides)
        with (
            patch(f"{MODULE}.generate_credentials_for_roles") as credentials,
            patch(f"{MODULE}.generate_user_passwords") as users,
        ):
            rotated = reset_credentials(**arguments)
        return rotated, credentials, users

    def _document(self):
        return load_document(self.host_vars_file)

    def test_every_generated_credential_is_dropped(self):
        self._reset()
        credentials = self._document()["applications"]["web-app-a"]["credentials"]
        self.assertNotIn("api_key", credentials)
        self.assertNotIn("secret", credentials["recaptcha"])

    def test_an_operator_supplied_plain_value_survives(self):
        self._reset()
        credentials = self._document()["applications"]["web-app-a"]["credentials"]
        self.assertEqual(credentials["smtp_password"], "")

    def test_an_excluded_application_is_untouched(self):
        self._reset(exclude={"administrator", "web-app-keycloak"})
        credentials = self._document()["applications"]["web-app-keycloak"][
            "credentials"
        ]
        self.assertIn("database_password", credentials)

    def test_an_excluded_user_keeps_its_password(self):
        self._reset()
        users = self._document()["users"]
        self.assertIn("password", users["administrator"])
        self.assertNotIn("password", users["newsletter"])

    def test_an_undeclared_user_keeps_its_password(self):
        self._reset()
        self.assertIn("password", self._document()["users"]["biber"])

    def test_the_become_password_is_untouched(self):
        self._reset()
        self.assertIn("ansible_become_password", self._document())

    def test_unrelated_keys_and_comments_survive(self):
        self._reset()
        text = self.host_vars_file.read_text(encoding="utf-8")
        self.assertIn("This comment must survive the rotation.", text)
        self.assertTrue(self._document()["applications"]["web-app-a"]["features"])

    def test_the_dropped_values_are_regenerated(self):
        _, credentials, users = self._reset()
        credentials.assert_called_once()
        users.assert_called_once()

    def test_only_schema_leaves_the_users_alone(self):
        _, credentials, users = self._reset(users=False)
        self.assertIn("password", self._document()["users"]["newsletter"])
        users.assert_not_called()
        credentials.assert_called_once()

    def test_only_users_leaves_the_credentials_alone(self):
        _, credentials, users = self._reset(schema=False)
        applications = self._document()["applications"]
        self.assertIn("api_key", applications["web-app-a"]["credentials"])
        credentials.assert_not_called()
        users.assert_called_once()

    def test_the_rotated_count_covers_both_sections(self):
        rotated, _, _ = self._reset()
        self.assertEqual(rotated, 4)

    def test_rotating_nothing_aborts(self):
        with self.assertRaises(SystemExit):
            self._reset(schema=False, users=False)

    def test_the_result_is_still_loadable_yaml(self):
        self._reset()
        with self.host_vars_file.open(encoding="utf-8") as handle:
            self.assertIsNotNone(YAML(typ="rt").load(handle))


if __name__ == "__main__":
    unittest.main()
