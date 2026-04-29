import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

import yaml

from cli.create.credentials import ask_for_confirmation, main
from utils.handler.vault import VaultHandler


class TestCreateCredentials(unittest.TestCase):
    def test_ask_for_confirmation_yes(self):
        with unittest.mock.patch("builtins.input", return_value="y"):
            self.assertTrue(ask_for_confirmation("test_key"))

    def test_ask_for_confirmation_no(self):
        with unittest.mock.patch("builtins.input", return_value="n"):
            self.assertFalse(ask_for_confirmation("test_key"))

    def test_vault_encrypt_string_success(self):
        handler = VaultHandler("dummy_pw_file")
        # Mock subprocess.run to simulate successful vault encryption
        fake_output = "Encrypted data"
        completed = subprocess.CompletedProcess(
            args=["ansible-vault"], returncode=0, stdout=fake_output, stderr=""
        )
        with unittest.mock.patch("subprocess.run", return_value=completed) as proc_run:
            result = handler.encrypt_string("plain_val", "name")
            proc_run.assert_called_once()
            self.assertEqual(result, fake_output)

    def test_vault_encrypt_string_failure(self):
        handler = VaultHandler("dummy_pw_file")
        # Mock subprocess.run to simulate failure
        completed = subprocess.CompletedProcess(
            args=["ansible-vault"], returncode=1, stdout="", stderr="error"
        )
        with unittest.mock.patch("subprocess.run", return_value=completed):
            with self.assertRaises(RuntimeError):
                handler.encrypt_string("plain_val", "name")

    def test_main_overrides_and_file_writing(self):
        # Setup temporary files for role-path vars and inventory
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = os.path.join(tmpdir, "role")
            os.makedirs(os.path.join(role_path, "meta"))
            os.makedirs(os.path.join(role_path, "vars"))
            # Create vars/main.yml with application_id
            main_vars = {"application_id": "app_test"}
            with open(os.path.join(role_path, "vars", "main.yml"), "w") as f:
                yaml.dump(main_vars, f)
            # Create config/main.yml with features disabled
            config = {"features": {"central_database": False}}
            with open(os.path.join(role_path, "meta", "services.yml"), "w") as f:
                yaml.dump(config, f)
            # Create schema.yml defining plain credential
            schema = {
                "credentials": {
                    "api_key": {
                        "description": "API key",
                        "algorithm": "plain",
                        "validation": {},
                    }
                }
            }
            with open(os.path.join(role_path, "meta", "schema.yml"), "w") as f:
                yaml.dump(schema, f)
            # Prepare inventory file
            inventory_file = os.path.join(tmpdir, "inventory.yml")
            with open(inventory_file, "w") as f:
                yaml.dump({}, f)
            vault_pw_file = os.path.join(tmpdir, "pw.txt")
            with open(vault_pw_file, "w") as f:
                f.write("pw")

            # Simulate ansible-vault encrypt_string output for api_key
            fake_snippet = "!vault |\n  $ANSIBLE_VAULT;1.1;AES256\n    ENCRYPTEDVALUE"
            completed = subprocess.CompletedProcess(
                args=["ansible-vault"], returncode=0, stdout=fake_snippet, stderr=""
            )
            with unittest.mock.patch("subprocess.run", return_value=completed):
                # Run main with override for credentials.api_key and force to skip prompt
                sys.argv = [
                    "create/credentials.py",
                    "--role-path",
                    role_path,
                    "--inventory-file",
                    inventory_file,
                    "--vault-password-file",
                    vault_pw_file,
                    "--set",
                    "credentials.api_key=SECRET",
                    "--force",
                ]
                # Should complete without error
                main()
                # Verify inventory file updated with vaulted api_key
                with open(inventory_file) as f:
                    data = yaml.safe_load(f)
                creds = data["applications"]["app_test"]["credentials"]
                self.assertIn("api_key", creds)
                # VaultScalar serializes to a vault block, safe_load returns a string containing the vault header
                self.assertIsInstance(creds["api_key"], str)
                self.assertTrue(creds["api_key"].lstrip().startswith("$ANSIBLE_VAULT"))

    def test_main_plain_algorithm_allow_empty_plain_sets_empty_string_without_vault(
        self,
    ):
        """
        When --allow-empty-plain is used, a 'plain' credential without override
        should be set to "" and *not* encrypted (no ansible-vault calls).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = os.path.join(tmpdir, "role")
            os.makedirs(os.path.join(role_path, "meta"))
            os.makedirs(os.path.join(role_path, "vars"))

            # vars/main.yml with application_id
            main_vars = {"application_id": "app_empty_plain"}
            with open(os.path.join(role_path, "vars", "main.yml"), "w") as f:
                yaml.dump(main_vars, f)

            # config/main.yml
            config = {"features": {"central_database": False}}
            with open(os.path.join(role_path, "meta", "services.yml"), "w") as f:
                yaml.dump(config, f)

            # schema/main.yml: plain credential *without* overrides
            schema = {
                "credentials": {
                    "api_key": {
                        "description": "API key",
                        "algorithm": "plain",
                        "validation": {},
                    }
                }
            }
            with open(os.path.join(role_path, "meta", "schema.yml"), "w") as f:
                yaml.dump(schema, f)

            # Empty inventory file
            inventory_file = os.path.join(tmpdir, "inventory.yml")
            with open(inventory_file, "w") as f:
                yaml.dump({}, f)

            # Vault password file
            vault_pw_file = os.path.join(tmpdir, "pw.txt")
            with open(vault_pw_file, "w") as f:
                f.write("pw")

            # Ensure ansible-vault is *not* called at all in this scenario
            def fail_run(*_args, **_kwargs):
                raise AssertionError(
                    "ansible-vault must not be called for allow_empty_plain + empty plain"
                )

            with unittest.mock.patch("subprocess.run", side_effect=fail_run):
                sys.argv = [
                    "create/credentials.py",
                    "--role-path",
                    role_path,
                    "--inventory-file",
                    inventory_file,
                    "--vault-password-file",
                    vault_pw_file,
                    "--allow-empty-plain",
                ]
                main()

            with open(inventory_file) as f:
                data = yaml.safe_load(f)
            creds = data["applications"]["app_empty_plain"]["credentials"]
            # api_key should exist and be an empty string, not a vault block
            self.assertIn("api_key", creds)
            self.assertEqual(creds["api_key"], "")
