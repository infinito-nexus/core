import base64
import tempfile
from pathlib import Path
from unittest import TestCase, main, mock

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from utils.handler.vault import VaultScalar
from utils.manager.inventory import InventoryManager
from utils.manager.value_generator import ValueGenerator
from utils.roles.mapping import (
    ROLE_FILE_META_SCHEMA,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


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

            (role_path / ROLE_FILE_META_SCHEMA).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_VARS_MAIN).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_META_SERVICES).write_text("{}", encoding="utf-8")
            inv_path.write_text("{}", encoding="utf-8")

            inventory_path = inv_path

            def fake_load_yaml(path):
                p = Path(path)
                if p == inventory_path:
                    return {}
                if p == role_path / ROLE_FILE_META_SCHEMA:
                    return {}
                if p == role_path / ROLE_FILE_VARS_MAIN:
                    return {}
                if p == role_path / ROLE_FILE_META_SERVICES:
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

            (role_path / ROLE_FILE_META_SCHEMA).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_VARS_MAIN).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_META_SERVICES).write_text("{}", encoding="utf-8")

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
                if p == role_path / ROLE_FILE_META_SCHEMA:
                    return schema_data
                if p == role_path / ROLE_FILE_VARS_MAIN:
                    return {"application_id": "app_test"}
                if p == role_path / ROLE_FILE_META_SERVICES:
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
                    overrides={},
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

            (role_path / ROLE_FILE_META_SCHEMA).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_VARS_MAIN).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_META_SERVICES).write_text("{}", encoding="utf-8")

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
                if p == role_path / ROLE_FILE_META_SCHEMA:
                    return schema_data
                if p == role_path / ROLE_FILE_VARS_MAIN:
                    return {"application_id": "app_test"}
                if p == role_path / ROLE_FILE_META_SERVICES:
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
                    overrides={},
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

            (role_path / ROLE_FILE_META_SCHEMA).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_VARS_MAIN).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_META_SERVICES).write_text("{}", encoding="utf-8")

            inventory_path = inv_path

            schema_data = {
                "credentials": {
                    "sso_proxy_cookie_secret": {
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
                if p == role_path / ROLE_FILE_META_SCHEMA:
                    return schema_data
                if p == role_path / ROLE_FILE_VARS_MAIN:
                    return {"application_id": "app_test"}
                if p == role_path / ROLE_FILE_META_SERVICES:
                    return {"sso": {"enabled": True}}
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
                self.assertEqual(creds["sso_proxy_cookie_secret"], "generated-secret")
                mock_vault.encrypt_string.assert_not_called()

    def test_oauth2_dynamic_flag_seeds_cookie_secret(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "role"
            inv_path = Path(tmpdir) / "inventory.yml"
            role_path.mkdir(parents=True, exist_ok=True)
            (role_path / "meta").mkdir(parents=True, exist_ok=True)
            (role_path / "vars").mkdir(parents=True, exist_ok=True)
            (role_path / "config").mkdir(parents=True, exist_ok=True)
            inv_path.write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_META_SCHEMA).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_VARS_MAIN).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_META_SERVICES).write_text("{}", encoding="utf-8")

            schema_data = {
                "credentials": {
                    "sso_proxy_cookie_secret": {
                        "description": "Cookie secret",
                        "algorithm": "plain",
                        "validation": {},
                    }
                }
            }

            def fake_load_yaml(path):
                p = Path(path)
                if p == inv_path:
                    return {"applications": {}}
                if p == role_path / ROLE_FILE_META_SCHEMA:
                    return schema_data
                if p == role_path / ROLE_FILE_VARS_MAIN:
                    return {"application_id": "app_test"}
                if p == role_path / ROLE_FILE_META_SERVICES:
                    return {
                        "sso": {
                            "enabled": "{{ 'web-app-keycloak' in group_names }}",
                            "shared": "{{ 'web-app-keycloak' in group_names }}",
                        }
                    }
                return {}

            with (
                mock.patch(
                    "utils.manager.inventory.YamlHandler.load_yaml",
                    side_effect=fake_load_yaml,
                ),
                mock.patch("utils.manager.inventory.VaultHandler"),
                mock.patch.object(
                    ValueGenerator, "generate_value", return_value="dynamic-secret"
                ),
            ):
                mgr = InventoryManager(
                    role_path=role_path,
                    inventory_path=inv_path,
                    vault_pw="dummy",
                    overrides={},
                    allow_empty_plain=True,
                )
                inv = mgr.apply_schema()
                creds = inv["applications"]["app_test"]["credentials"]
                self.assertEqual(creds["sso_proxy_cookie_secret"], "dynamic-secret")

    def test_oauth2_disabled_skips_cookie_secret(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "role"
            inv_path = Path(tmpdir) / "inventory.yml"
            role_path.mkdir(parents=True, exist_ok=True)
            (role_path / "meta").mkdir(parents=True, exist_ok=True)
            (role_path / "vars").mkdir(parents=True, exist_ok=True)
            (role_path / "config").mkdir(parents=True, exist_ok=True)
            inv_path.write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_META_SCHEMA).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_VARS_MAIN).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_META_SERVICES).write_text("{}", encoding="utf-8")

            def fake_load_yaml(path):
                p = Path(path)
                if p == inv_path:
                    return {"applications": {}}
                if p == role_path / ROLE_FILE_META_SCHEMA:
                    return {"credentials": {}}
                if p == role_path / ROLE_FILE_VARS_MAIN:
                    return {"application_id": "app_test"}
                if p == role_path / ROLE_FILE_META_SERVICES:
                    return {"sso": {"enabled": False}}
                return {}

            with (
                mock.patch(
                    "utils.manager.inventory.YamlHandler.load_yaml",
                    side_effect=fake_load_yaml,
                ),
                mock.patch("utils.manager.inventory.VaultHandler"),
                mock.patch.object(
                    ValueGenerator, "generate_value", return_value="should-not-fire"
                ),
            ):
                mgr = InventoryManager(
                    role_path=role_path,
                    inventory_path=inv_path,
                    vault_pw="dummy",
                    overrides={},
                    allow_empty_plain=True,
                )
                inv = mgr.apply_schema()
                creds = (
                    inv.get("applications", {})
                    .get("app_test", {})
                    .get("credentials", {})
                )
                self.assertNotIn("sso_proxy_cookie_secret", creds)

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

            (role_path / ROLE_FILE_META_SCHEMA).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_VARS_MAIN).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_META_SERVICES).write_text("{}", encoding="utf-8")

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
                if p == role_path / ROLE_FILE_META_SCHEMA:
                    return schema_data
                if p == role_path / ROLE_FILE_VARS_MAIN:
                    return {"application_id": "app_test"}
                if p == role_path / ROLE_FILE_META_SERVICES:
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

            (role_path / ROLE_FILE_META_SCHEMA).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_VARS_MAIN).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_META_SERVICES).write_text("{}", encoding="utf-8")

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
                if p == role_path / ROLE_FILE_META_SCHEMA:
                    return schema_data
                if p == role_path / ROLE_FILE_VARS_MAIN:
                    return {"application_id": "app_test"}
                if p == role_path / ROLE_FILE_META_SERVICES:
                    return {}
                return {}

            with (
                mock.patch(
                    "utils.manager.inventory.YamlHandler.load_yaml",
                    side_effect=fake_load_yaml,
                ),
                mock.patch("utils.manager.inventory.VaultHandler") as mock_vault_cls,
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

    def test_vapid_keys_generated_through_schema_are_linked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "role"
            inv_path = Path(tmpdir) / "inventory.yml"

            role_path.mkdir(parents=True, exist_ok=True)
            (role_path / "meta").mkdir(parents=True, exist_ok=True)
            (role_path / "vars").mkdir(parents=True, exist_ok=True)
            (role_path / "config").mkdir(parents=True, exist_ok=True)
            inv_path.write_text("{}", encoding="utf-8")

            (role_path / ROLE_FILE_META_SCHEMA).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_VARS_MAIN).write_text("{}", encoding="utf-8")
            (role_path / ROLE_FILE_META_SERVICES).write_text("{}", encoding="utf-8")

            schema_data = {
                "credentials": {
                    "vapid_private_key": {
                        "description": "Private VAPID key",
                        "algorithm": "vapid_private",
                        "validation": {},
                    },
                    "vapid_public_key": {
                        "description": "Public VAPID key",
                        "algorithm": "vapid_public",
                        "validation": {},
                    },
                }
            }

            def fake_load_yaml(path):
                p = Path(path)
                if p == inv_path:
                    return {"applications": {}}
                if p == role_path / ROLE_FILE_META_SCHEMA:
                    return schema_data
                if p == role_path / ROLE_FILE_VARS_MAIN:
                    return {"application_id": "app_test"}
                if p == role_path / ROLE_FILE_META_SERVICES:
                    return {}
                return {}

            captured = {}

            def fake_encrypt(plain, key):
                captured[key] = plain
                return "!vault |\n  $ANSIBLE_VAULT;1.1;AES256\n    ENCRYPTED"

            with (
                mock.patch(
                    "utils.manager.inventory.YamlHandler.load_yaml",
                    side_effect=fake_load_yaml,
                ),
                mock.patch("utils.manager.inventory.VaultHandler") as mock_vault_cls,
            ):
                mock_vault = mock_vault_cls.return_value
                mock_vault.encrypt_string.side_effect = fake_encrypt

                mgr = InventoryManager(
                    role_path=role_path,
                    inventory_path=inv_path,
                    vault_pw="dummy",
                    overrides={},
                    allow_empty_plain=False,
                )
                mgr.apply_schema()

            private = captured["vapid_private_key"]
            public = captured["vapid_public_key"]
            scalar = int.from_bytes(_b64url_decode(private), "big")
            derived = ec.derive_private_key(scalar, ec.SECP256R1())
            expected_point = derived.public_key().public_bytes(
                Encoding.X962, PublicFormat.UncompressedPoint
            )
            self.assertEqual(_b64url_decode(public), expected_point)


class TestInventoryManagerVariant(TestCase):
    def _make_role(self, tmp: Path, app_id: str = "svc-bkp-container-2-local") -> Path:
        role_path = tmp / "roles" / app_id
        (role_path / "meta").mkdir(parents=True)
        (role_path / "vars").mkdir(parents=True)
        (role_path / ROLE_FILE_VARS_MAIN).write_text(
            f"application_id: {app_id}\n", encoding="utf-8"
        )
        (role_path / ROLE_FILE_META_SCHEMA).write_text("{}", encoding="utf-8")
        (role_path / ROLE_FILE_META_SERVICES).write_text("{}", encoding="utf-8")
        return role_path

    def test_variant_none_uses_base_meta_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            role_path = self._make_role(tmp)
            inv_path = tmp / "inv.yml"
            inv_path.write_text("{}", encoding="utf-8")

            with mock.patch("utils.manager.inventory.VaultHandler"):
                mgr = InventoryManager(
                    role_path=role_path,
                    inventory_path=inv_path,
                    vault_pw="dummy",
                    overrides={},
                )
            with mock.patch(
                "utils.manager.inventory.get_variants",
                side_effect=AssertionError(
                    "get_variants must not be called when variant is None"
                ),
            ):
                cfg = mgr.load_role_config_by_path(role_path)
            self.assertEqual(cfg, {})

    def test_variant_set_uses_variants_overlay_for_root_role(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            app_id = "svc-bkp-container-2-local"
            role_path = self._make_role(tmp, app_id=app_id)
            inv_path = tmp / "inv.yml"
            inv_path.write_text("{}", encoding="utf-8")

            variant_payload = {
                "services": {
                    "ldap": {"enabled": True, "shared": True},
                }
            }
            with (
                mock.patch("utils.manager.inventory.VaultHandler"),
                mock.patch(
                    "utils.manager.inventory.get_variants",
                    return_value={app_id: [{}, {}, variant_payload]},
                ),
            ):
                mgr = InventoryManager(
                    role_path=role_path,
                    inventory_path=inv_path,
                    vault_pw="dummy",
                    overrides={},
                    variant=2,
                )
                cfg = mgr.load_role_config_by_path(role_path)

            self.assertEqual(cfg, variant_payload)

    def test_variant_only_overlays_root_not_other_role_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            root_app = "svc-bkp-container-2-local"
            other_app = "svc-db-openldap"
            root_path = self._make_role(tmp, app_id=root_app)
            other_path = self._make_role(tmp, app_id=other_app)
            inv_path = tmp / "inv.yml"
            inv_path.write_text("{}", encoding="utf-8")

            variant_payload = {"services": {"ldap": {"enabled": True, "shared": True}}}
            with (
                mock.patch("utils.manager.inventory.VaultHandler"),
                mock.patch(
                    "utils.manager.inventory.get_variants",
                    return_value={
                        root_app: [{}, variant_payload],
                        other_app: [{"services": {"poisoned": True}}],
                    },
                ),
            ):
                mgr = InventoryManager(
                    role_path=root_path,
                    inventory_path=inv_path,
                    vault_pw="dummy",
                    overrides={},
                    variant=1,
                )
                root_cfg = mgr.load_role_config_by_path(root_path)
                other_cfg = mgr.load_role_config_by_path(other_path)

            self.assertEqual(root_cfg, variant_payload)
            self.assertEqual(other_cfg, {})

    def test_variant_out_of_range_falls_back_to_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            app_id = "svc-bkp-container-2-local"
            role_path = self._make_role(tmp, app_id=app_id)
            inv_path = tmp / "inv.yml"
            inv_path.write_text("{}", encoding="utf-8")

            with (
                mock.patch("utils.manager.inventory.VaultHandler"),
                mock.patch(
                    "utils.manager.inventory.get_variants",
                    return_value={app_id: [{}]},
                ),
            ):
                mgr = InventoryManager(
                    role_path=role_path,
                    inventory_path=inv_path,
                    vault_pw="dummy",
                    overrides={},
                    variant=42,
                )
                cfg = mgr.load_role_config_by_path(role_path)
            self.assertEqual(cfg, {})


if __name__ == "__main__":
    main()
