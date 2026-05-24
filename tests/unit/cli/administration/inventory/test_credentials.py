import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from cli.administration.inventory.credentials import ask_for_confirmation, main
from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.handler.vault import VaultHandler
from utils.roles.mapping import (
    ROLE_FILE_META_SCHEMA,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)


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
        with (
            unittest.mock.patch("subprocess.run", return_value=completed),
            self.assertRaises(RuntimeError),
        ):
            handler.encrypt_string("plain_val", "name")

    def test_main_overrides_and_file_writing(self):
        # Setup temporary files for role-path vars and inventory
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = str(Path(tmpdir) / "role")
            Path(str(Path(role_path) / "meta")).mkdir(parents=True)
            Path(str(Path(role_path) / "vars")).mkdir(parents=True)
            # Create vars/main.yml with application_id
            main_vars = {"application_id": "app_test"}
            dump_yaml(str(Path(role_path) / ROLE_FILE_VARS_MAIN), main_vars)
            # Create config/main.yml with features disabled
            config = {"features": {"central_database": False}}
            dump_yaml(str(Path(role_path) / ROLE_FILE_META_SERVICES), config)
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
            dump_yaml(str(Path(role_path) / ROLE_FILE_META_SCHEMA), schema)
            # Prepare inventory file
            inventory_file = str(Path(tmpdir) / "inventory.yml")
            dump_yaml(inventory_file, {})
            vault_pw_file = str(Path(tmpdir) / "pw.txt")
            with Path(vault_pw_file).open("w") as f:
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
                data = load_yaml_any(inventory_file)
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
            role_path = str(Path(tmpdir) / "role")
            Path(str(Path(role_path) / "meta")).mkdir(parents=True)
            Path(str(Path(role_path) / "vars")).mkdir(parents=True)

            # vars/main.yml with application_id
            main_vars = {"application_id": "app_empty_plain"}
            dump_yaml(str(Path(role_path) / ROLE_FILE_VARS_MAIN), main_vars)

            # config/main.yml
            config = {"features": {"central_database": False}}
            dump_yaml(str(Path(role_path) / ROLE_FILE_META_SERVICES), config)

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
            dump_yaml(str(Path(role_path) / ROLE_FILE_META_SCHEMA), schema)

            # Empty inventory file
            inventory_file = str(Path(tmpdir) / "inventory.yml")
            dump_yaml(inventory_file, {})

            # Vault password file
            vault_pw_file = str(Path(tmpdir) / "pw.txt")
            with Path(vault_pw_file).open("w") as f:
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

            data = load_yaml_any(inventory_file)
            creds = data["applications"]["app_empty_plain"]["credentials"]
            # api_key should exist and be an empty string, not a vault block
            self.assertIn("api_key", creds)
            self.assertEqual(creds["api_key"], "")

    def test_main_forwards_variant_to_inventory_manager(self):
        """The `--variant` CLI flag must reach `InventoryManager(variant=)` so
        shared-provider discovery uses the variants.yml overlay."""
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = str(Path(tmpdir) / "role")
            Path(str(Path(role_path) / "meta")).mkdir(parents=True)
            Path(str(Path(role_path) / "vars")).mkdir(parents=True)
            dump_yaml(
                str(Path(role_path) / ROLE_FILE_VARS_MAIN),
                {"application_id": "app_test"},
            )
            dump_yaml(str(Path(role_path) / ROLE_FILE_META_SERVICES), {})
            dump_yaml(str(Path(role_path) / ROLE_FILE_META_SCHEMA), {})

            inventory_file = str(Path(tmpdir) / "inventory.yml")
            dump_yaml(inventory_file, {})
            vault_pw_file = str(Path(tmpdir) / "pw.txt")
            with Path(vault_pw_file).open("w") as f:
                f.write("pw")

            captured: dict = {}

            class FakeManager:
                def __init__(self, **kwargs):
                    captured.update(kwargs)
                    self.app_id = kwargs.get("overrides", {}).get(
                        "_fake_app_id", "app_test"
                    )
                    self.vault_handler = None
                    self.schema = {}
                    self.inventory = {}

                def apply_schema(self):
                    return {"applications": {}}

            with unittest.mock.patch(
                "cli.administration.inventory.credentials.__main__.InventoryManager",
                FakeManager,
            ):
                sys.argv = [
                    "credentials",
                    "--role-path",
                    role_path,
                    "--inventory-file",
                    inventory_file,
                    "--vault-password-file",
                    vault_pw_file,
                    "--snippet",
                    "--variant",
                    "2",
                ]
                main()

            self.assertEqual(captured.get("variant"), 2)

    def test_main_variant_defaults_to_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = str(Path(tmpdir) / "role")
            Path(str(Path(role_path) / "meta")).mkdir(parents=True)
            Path(str(Path(role_path) / "vars")).mkdir(parents=True)
            dump_yaml(
                str(Path(role_path) / ROLE_FILE_VARS_MAIN),
                {"application_id": "app_test"},
            )
            dump_yaml(str(Path(role_path) / ROLE_FILE_META_SERVICES), {})
            dump_yaml(str(Path(role_path) / ROLE_FILE_META_SCHEMA), {})

            inventory_file = str(Path(tmpdir) / "inventory.yml")
            dump_yaml(inventory_file, {})
            vault_pw_file = str(Path(tmpdir) / "pw.txt")
            with Path(vault_pw_file).open("w") as f:
                f.write("pw")

            captured: dict = {}

            class FakeManager:
                def __init__(self, **kwargs):
                    captured.update(kwargs)
                    self.app_id = "app_test"
                    self.vault_handler = None
                    self.schema = {}
                    self.inventory = {}

                def apply_schema(self):
                    return {"applications": {}}

            with unittest.mock.patch(
                "cli.administration.inventory.credentials.__main__.InventoryManager",
                FakeManager,
            ):
                sys.argv = [
                    "credentials",
                    "--role-path",
                    role_path,
                    "--inventory-file",
                    inventory_file,
                    "--vault-password-file",
                    vault_pw_file,
                    "--snippet",
                ]
                main()

            self.assertIsNone(captured.get("variant"))
