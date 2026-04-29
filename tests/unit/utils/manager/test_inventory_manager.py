# tests/unit/utils/manager/test_inventory_manager.py

import tempfile
from pathlib import Path
from unittest import TestCase, main, mock

from utils.manager.inventory import InventoryManager  # type: ignore
from utils.handler.vault import VaultScalar  # type: ignore
from utils.manager.value_generator import ValueGenerator  # type: ignore


class TestInventoryManager(TestCase):
    def test_load_application_id_missing_exits(self):
        """
        If vars/main.yml does not contain application_id, InventoryManager
        must print an error and exit with code 1.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "role"
            inv_path = Path(tmpdir) / "inventory.yml"

            role_path.mkdir(parents=True, exist_ok=True)
            (role_path / "meta").mkdir(parents=True, exist_ok=True)
            (role_path / "vars").mkdir(parents=True, exist_ok=True)
            (role_path / "config").mkdir(parents=True, exist_ok=True)

            # IMPORTANT: ensure files exist for .exists() checks
            (role_path / "meta" / "schema.yml").write_text("{}", encoding="utf-8")
            (role_path / "vars" / "main.yml").write_text("{}", encoding="utf-8")
            (role_path / "meta" / "services.yml").write_text("{}", encoding="utf-8")
            inv_path.write_text("{}", encoding="utf-8")

            inventory_path = inv_path

            def fake_load_yaml(path):
                p = Path(path)
                if p == inventory_path:
                    return {}
                if p == role_path / "meta" / "schema.yml":
                    return {}
                if p == role_path / "vars" / "main.yml":
                    return {}  # missing application_id on purpose
                if p == role_path / "meta" / "services.yml":
                    # Per req-008: meta/services.yml file root IS the
                    # services map (no `compose.services` envelope).
                    return {}
                return {}

            with (
                mock.patch(
                    "utils.manager.inventory.YamlHandler.load_yaml",
                    side_effect=fake_load_yaml,
                ),
                mock.patch("utils.manager.inventory.VaultHandler"),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    InventoryManager(
                        role_path=role_path,
                        inventory_path=inventory_path,
                        vault_pw="dummy",
                        overrides={},
                    )
                self.assertEqual(ctx.exception.code, 1)

    def test_plain_without_override_and_allow_empty_plain_exits(self):
        """
        For a `plain` algorithm credential, if no override is provided and
        allow_empty_plain=False, apply_schema must exit.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "role"
            inv_path = Path(tmpdir) / "inventory.yml"

            role_path.mkdir(parents=True, exist_ok=True)
            (role_path / "meta").mkdir(parents=True, exist_ok=True)
            (role_path / "vars").mkdir(parents=True, exist_ok=True)
            (role_path / "config").mkdir(parents=True, exist_ok=True)
            inv_path.write_text("{}", encoding="utf-8")

            # IMPORTANT: ensure files exist for .exists() checks
            (role_path / "meta" / "schema.yml").write_text("{}", encoding="utf-8")
            (role_path / "vars" / "main.yml").write_text("{}", encoding="utf-8")
            (role_path / "meta" / "services.yml").write_text("{}", encoding="utf-8")

            inventory_path = inv_path

            schema_data = {
                "credentials": {
                    "api_key": {
                        "description": "API key",
                        "algorithm": "plain",
                        "validation": {},
                    }
                }
            }

            def fake_load_yaml(path):
                p = Path(path)
                if p == inventory_path:
                    return {"applications": {}}
                if p == role_path / "meta" / "schema.yml":
                    return schema_data
                if p == role_path / "vars" / "main.yml":
                    return {"application_id": "app_test"}
                if p == role_path / "meta" / "services.yml":
                    # Per req-008: meta/services.yml file root IS the
                    # services map (no `compose.services` envelope).
                    return {}
                return {}

            with (
                mock.patch(
                    "utils.manager.inventory.YamlHandler.load_yaml",
                    side_effect=fake_load_yaml,
                ),
                mock.patch("utils.manager.inventory.VaultHandler"),
            ):
                mgr = InventoryManager(
                    role_path=role_path,
                    inventory_path=inventory_path,
                    vault_pw="dummy",
                    overrides={},  # no plain override
                    allow_empty_plain=False,
                )
                with self.assertRaises(SystemExit) as ctx:
                    mgr.apply_schema()
                self.assertEqual(ctx.exception.code, 1)

    def test_plain_with_allow_empty_plain_sets_empty_string_unencrypted(self):
        """
        For a `plain` algorithm credential, if no override is provided and
        allow_empty_plain=True, the credential should be set to "" and must NOT be encrypted.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "role"
            inv_path = Path(tmpdir) / "inventory.yml"

            role_path.mkdir(parents=True, exist_ok=True)
            (role_path / "meta").mkdir(parents=True, exist_ok=True)
            (role_path / "vars").mkdir(parents=True, exist_ok=True)
            (role_path / "config").mkdir(parents=True, exist_ok=True)
            inv_path.write_text("{}", encoding="utf-8")

            # IMPORTANT: ensure files exist for .exists() checks
            (role_path / "meta" / "schema.yml").write_text("{}", encoding="utf-8")
            (role_path / "vars" / "main.yml").write_text("{}", encoding="utf-8")
            (role_path / "meta" / "services.yml").write_text("{}", encoding="utf-8")

            inventory_path = inv_path

            schema_data = {
                "credentials": {
                    "api_key": {
                        "description": "API key",
                        "algorithm": "plain",
                        "validation": {},
                    }
                }
            }

            def fake_load_yaml(path):
                p = Path(path)
                if p == inventory_path:
                    return {"applications": {}}
                if p == role_path / "meta" / "schema.yml":
                    return schema_data
                if p == role_path / "vars" / "main.yml":
                    return {"application_id": "app_test"}
                if p == role_path / "meta" / "services.yml":
                    # Per req-008: meta/services.yml file root IS the
                    # services map (no `compose.services` envelope).
                    return {}
                return {}

            with (
                mock.patch(
                    "utils.manager.inventory.YamlHandler.load_yaml",
                    side_effect=fake_load_yaml,
                ),
                mock.patch("utils.manager.inventory.VaultHandler") as mock_vault_cls,
            ):
                mock_vault = mock_vault_cls.return_value
                mock_vault.encrypt_string.return_value = (
                    "!vault |\n  $ANSIBLE_VAULT;1.1;AES256\n    ENCRYPTED"
                )

                mgr = InventoryManager(
                    role_path=role_path,
                    inventory_path=inventory_path,
                    vault_pw="dummy",
                    overrides={},  # no override for plain
                    allow_empty_plain=True,
                )
                inv = mgr.apply_schema()

                creds = inv["applications"]["app_test"]["credentials"]
                self.assertIn("api_key", creds)
                self.assertEqual(creds["api_key"], "")

                mock_vault.encrypt_string.assert_not_called()

    def test_plain_preserves_existing_generated_value(self):
        """
        If a plain credential was already populated by special-role logic,
        allow_empty_plain must not overwrite it with an empty string.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "role"
            inv_path = Path(tmpdir) / "inventory.yml"

            role_path.mkdir(parents=True, exist_ok=True)
            (role_path / "meta").mkdir(parents=True, exist_ok=True)
            (role_path / "vars").mkdir(parents=True, exist_ok=True)
            (role_path / "config").mkdir(parents=True, exist_ok=True)
            inv_path.write_text("{}", encoding="utf-8")

            (role_path / "meta" / "schema.yml").write_text("{}", encoding="utf-8")
            (role_path / "vars" / "main.yml").write_text("{}", encoding="utf-8")
            (role_path / "meta" / "services.yml").write_text("{}", encoding="utf-8")

            inventory_path = inv_path

            schema_data = {
                "credentials": {
                    "oauth2_proxy_cookie_secret": {
                        "description": "Cookie secret",
                        "algorithm": "plain",
                        "validation": {},
                    }
                }
            }

            def fake_load_yaml(path):
                p = Path(path)
                if p == inventory_path:
                    return {"applications": {}}
                if p == role_path / "meta" / "schema.yml":
                    return schema_data
                if p == role_path / "vars" / "main.yml":
                    return {"application_id": "app_test"}
                if p == role_path / "meta" / "services.yml":
                    # Per req-008 the file root IS the services map
                    # (no `compose.services` envelope).
                    return {"oauth2": {"enabled": True}}
                return {}

            with (
                mock.patch(
                    "utils.manager.inventory.YamlHandler.load_yaml",
                    side_effect=fake_load_yaml,
                ),
                mock.patch("utils.manager.inventory.VaultHandler") as mock_vault_cls,
                mock.patch.object(
                    ValueGenerator, "generate_value", return_value="generated-secret"
                ),
            ):
                mock_vault = mock_vault_cls.return_value
                mgr = InventoryManager(
                    role_path=role_path,
                    inventory_path=inventory_path,
                    vault_pw="dummy",
                    overrides={},
                    allow_empty_plain=True,
                )
                inv = mgr.apply_schema()

                creds = inv["applications"]["app_test"]["credentials"]
                self.assertEqual(
                    creds["oauth2_proxy_cookie_secret"], "generated-secret"
                )
                mock_vault.encrypt_string.assert_not_called()

    def test_non_plain_algorithm_encrypts_and_sets_vaultscalar(self):
        """
        For non-plain algorithms, apply_schema must generate a value (via ValueGenerator)
        and encrypt it into a VaultScalar.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "role"
            inv_path = Path(tmpdir) / "inventory.yml"

            role_path.mkdir(parents=True, exist_ok=True)
            (role_path / "meta").mkdir(parents=True, exist_ok=True)
            (role_path / "vars").mkdir(parents=True, exist_ok=True)
            (role_path / "config").mkdir(parents=True, exist_ok=True)
            inv_path.write_text("{}", encoding="utf-8")

            # IMPORTANT: ensure files exist for .exists() checks
            (role_path / "meta" / "schema.yml").write_text("{}", encoding="utf-8")
            (role_path / "vars" / "main.yml").write_text("{}", encoding="utf-8")
            (role_path / "meta" / "services.yml").write_text("{}", encoding="utf-8")

            inventory_path = inv_path

            schema_data = {
                "credentials": {
                    "api_key": {
                        "description": "API key",
                        "algorithm": "random_hex_16",
                        "validation": {},
                    }
                }
            }

            def fake_load_yaml(path):
                p = Path(path)
                if p == inventory_path:
                    return {"applications": {}}
                if p == role_path / "meta" / "schema.yml":
                    return schema_data
                if p == role_path / "vars" / "main.yml":
                    return {"application_id": "app_test"}
                if p == role_path / "meta" / "services.yml":
                    # Per req-008: meta/services.yml file root IS the
                    # services map (no `compose.services` envelope).
                    return {}
                return {}

            fake_snippet = "!vault |\n  $ANSIBLE_VAULT;1.1;AES256\n    ENCRYPTEDVALUE"

            with (
                mock.patch(
                    "utils.manager.inventory.YamlHandler.load_yaml",
                    side_effect=fake_load_yaml,
                ),
                mock.patch("utils.manager.inventory.VaultHandler") as mock_vault_cls,
                mock.patch.object(
                    ValueGenerator, "generate_value", return_value="PLAINVAL"
                ),
            ):
                mock_vault = mock_vault_cls.return_value
                mock_vault.encrypt_string.return_value = fake_snippet

                mgr = InventoryManager(
                    role_path=role_path,
                    inventory_path=inventory_path,
                    vault_pw="dummy",
                    overrides={},
                    allow_empty_plain=False,
                )
                inv = mgr.apply_schema()

                creds = inv["applications"]["app_test"]["credentials"]
                self.assertIn("api_key", creds)
                value = creds["api_key"]

                self.assertIsInstance(value, VaultScalar)
                self.assertIn("$ANSIBLE_VAULT", str(value))

                mock_vault.encrypt_string.assert_called_once_with("PLAINVAL", "api_key")

    def test_recurse_skips_existing_dict_and_vaultscalar(self):
        """
        If the destination already contains:
          - a dict for a credential key, or
          - a VaultScalar for a credential key,
        recurse_credentials must skip re-encryption and leave existing values untouched.

        NOTE:
        InventoryManager now checks schema/config file existence on disk before loading,
        so we must create those files in the temp role directory.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "role"
            inv_path = Path(tmpdir) / "inventory.yml"

            role_path.mkdir(parents=True, exist_ok=True)
            (role_path / "meta").mkdir(parents=True, exist_ok=True)
            (role_path / "vars").mkdir(parents=True, exist_ok=True)
            (role_path / "config").mkdir(parents=True, exist_ok=True)
            inv_path.write_text("{}", encoding="utf-8")

            # IMPORTANT: ensure files exist for .exists() checks
            (role_path / "meta" / "schema.yml").write_text("{}", encoding="utf-8")
            (role_path / "vars" / "main.yml").write_text("{}", encoding="utf-8")
            (role_path / "meta" / "services.yml").write_text("{}", encoding="utf-8")

            inventory_path = inv_path

            existing_vault = VaultScalar("EXISTING_BODY")
            existing_dict = {"nested": "value"}

            inventory_data = {
                "applications": {
                    "app_test": {
                        "credentials": {
                            "already_vaulted": existing_vault,
                            "complex": existing_dict,
                        }
                    }
                }
            }

            schema_data = {
                "credentials": {
                    "already_vaulted": {
                        "description": "Vaulted",
                        "algorithm": "random_hex_16",
                        "validation": {},
                    },
                    "complex": {
                        "description": "Complex dict",
                        "algorithm": "random_hex_16",
                        "validation": {},
                    },
                }
            }

            def fake_load_yaml(path):
                p = Path(path)
                if p == inventory_path:
                    return inventory_data
                if p == role_path / "meta" / "schema.yml":
                    return schema_data
                if p == role_path / "vars" / "main.yml":
                    return {"application_id": "app_test"}
                if p == role_path / "meta" / "services.yml":
                    # No provider resolution / no special rules
                    # Per req-008: meta/services.yml file root IS the
                    # services map (no `compose.services` envelope).
                    return {}
                return {}

            with (
                mock.patch(
                    "utils.manager.inventory.YamlHandler.load_yaml",
                    side_effect=fake_load_yaml,
                ),
                mock.patch("utils.manager.inventory.VaultHandler") as mock_vault_cls,
                # Even though encryption is skipped, the current implementation
                # may still call ValueGenerator.generate_value() before checking
                # existing destination values. Keep it deterministic.
                mock.patch.object(
                    ValueGenerator, "generate_value", return_value="IGNORED"
                ),
            ):
                mock_vault = mock_vault_cls.return_value
                mock_vault.encrypt_string.side_effect = AssertionError(
                    "encrypt_string should not be called for existing VaultScalar/dict"
                )

                mgr = InventoryManager(
                    role_path=role_path,
                    inventory_path=inventory_path,
                    vault_pw="dummy",
                    overrides={},
                    allow_empty_plain=False,
                )
                inv = mgr.apply_schema()

                creds = inv["applications"]["app_test"]["credentials"]

                self.assertIn("already_vaulted", creds)
                self.assertIn("complex", creds)

                self.assertIs(creds["already_vaulted"], existing_vault)
                self.assertIs(creds["complex"], existing_dict)


if __name__ == "__main__":
    main()
