# tests/unit/cli/test_inventory_manager.py

import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

from utils.handler.yaml import YamlHandler
from utils.handler.vault import VaultHandler, VaultScalar
from utils.manager.inventory import InventoryManager
from utils.manager.value_generator import ValueGenerator


class TestInventoryManager(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for role and inventory files
        self.tmpdir = Path(tempfile.mkdtemp())

        # Patch YamlHandler.load_yaml
        self.load_yaml_patcher = patch.object(
            YamlHandler, "load_yaml", side_effect=self.fake_load_yaml
        )
        self.load_yaml_patcher.start()

        # Patch VaultHandler.encrypt_string with correct signature
        self.encrypt_patcher = patch.object(
            VaultHandler,
            "encrypt_string",
            new=lambda self, plain, key: f"{key}: !vault |\n    encrypted_{plain}",
        )
        self.encrypt_patcher.start()

    def tearDown(self):
        patch.stopall()
        shutil.rmtree(self.tmpdir)

    def fake_load_yaml(self, path):
        path = Path(path)

        # Return schema for meta/schema.yml
        if path.match("*/meta/schema.yml"):
            return {
                "credentials": {
                    "plain_cred": {
                        "description": "desc",
                        "algorithm": "plain",
                        "validation": {},
                    },
                    "nested": {
                        "inner": {
                            "description": "desc2",
                            "algorithm": "sha256",
                            "validation": {},
                        }
                    },
                }
            }

        # Return application_id for vars/main.yml
        if path.match("*/vars/main.yml"):
            return {"application_id": "testapp"}

        # Return docker service flags for meta/services.yml. Per req-008 the
        # file root IS the services map (no `compose.services` wrapper).
        if path.match("*/meta/services.yml"):
            return {
                "mariadb": {"enabled": True, "shared": True},
            }

        # Return empty inventory for inventory.yml
        if path.name == "inventory.yml":
            return {}
        raise FileNotFoundError(f"Unexpected load_yaml path: {path}")

    def test_load_application_id_missing(self):
        """Loading application_id without it should raise SystemExit."""
        role_dir = self.tmpdir / "role"
        (role_dir / "vars").mkdir(parents=True)
        (role_dir / "vars" / "main.yml").write_text("{}", encoding="utf-8")

        with patch.object(YamlHandler, "load_yaml", return_value={}):
            with self.assertRaises(SystemExit):
                InventoryManager(
                    role_dir, self.tmpdir / "inventory.yml", "pw", {}
                ).load_application_id(role_dir)

    def test_generate_value_algorithms(self):
        """
        Verify ValueGenerator.generate_value produces outputs of the expected form
        and contains no dollar signs (bcrypt is escaped).
        """
        vg = ValueGenerator()

        # random_hex → 64 bytes hex = 128 chars
        hex_val = vg.generate_value("random_hex")
        self.assertEqual(len(hex_val), 128)
        self.assertTrue(all(c in "0123456789abcdef" for c in hex_val))
        self.assertNotIn("$", hex_val)

        # sha256 → 64 hex chars
        sha256_val = vg.generate_value("sha256")
        self.assertEqual(len(sha256_val), 64)
        self.assertNotIn("$", sha256_val)

        # sha1 → 40 hex chars
        sha1_val = vg.generate_value("sha1")
        self.assertEqual(len(sha1_val), 40)
        self.assertNotIn("$", sha1_val)

        # bcrypt → contains no '$' after escaping
        bcrypt_val = vg.generate_value("bcrypt")
        self.assertNotIn("$", bcrypt_val)

        # alphanumeric → 64 chars
        alnum = vg.generate_value("alphanumeric")
        self.assertEqual(len(alnum), 64)
        self.assertTrue(alnum.isalnum())
        self.assertNotIn("$", alnum)

        # base64_prefixed_32 → starts with "base64:"
        b64 = vg.generate_value("base64_prefixed_32")
        self.assertTrue(b64.startswith("base64:"))
        self.assertNotIn("$", b64)

        # random_hex_16 → 32 hex chars
        hex16 = vg.generate_value("random_hex_16")
        self.assertEqual(len(hex16), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in hex16))
        self.assertNotIn("$", hex16)

    def test_apply_schema_and_recurse(self):
        """
        apply_schema should inject database password and vault plain_cred.
        """
        # Setup role directory (post-req-008: only meta/ + vars/).
        role_dir = self.tmpdir / "role"
        (role_dir / "meta").mkdir(parents=True, exist_ok=True)
        (role_dir / "vars").mkdir(parents=True, exist_ok=True)

        # IMPORTANT: files must exist because InventoryManager checks .exists()
        (role_dir / "meta" / "schema.yml").write_text("{}", encoding="utf-8")
        (role_dir / "meta" / "services.yml").write_text("{}", encoding="utf-8")
        (role_dir / "vars" / "main.yml").write_text("{}", encoding="utf-8")

        # Create empty inventory.yml
        inv_file = self.tmpdir / "inventory.yml"
        inv_file.write_text(" ", encoding="utf-8")

        # Provide override for plain_cred to avoid SystemExit
        overrides = {"credentials.plain_cred": "OVERRIDE_PLAIN"}

        # Instantiate manager with overrides
        mgr = InventoryManager(role_dir, inv_file, "pw", overrides=overrides)

        # IMPORTANT:
        # This unit test is NOT about transitive shared-provider resolution.
        with patch.object(
            InventoryManager, "resolve_schema_includes_recursive", return_value=[]
        ):
            # Patch ValueGenerator for predictable outputs
            with patch.object(
                ValueGenerator, "generate_value", side_effect=lambda alg: f"GEN_{alg}"
            ):
                result = mgr.apply_schema()

        apps = result["applications"]["testapp"]

        # credentials must exist now
        self.assertIn("credentials", apps)
        creds = apps["credentials"]

        # database_password comes from ValueGenerator.generate_value("alphanumeric")
        self.assertEqual(creds["database_password"], "GEN_alphanumeric")

        # plain_cred vaulted from override
        self.assertIsInstance(creds["plain_cred"], VaultScalar)

        # Per req-008 nested credential keys are supported and walked
        # recursively, so nested.inner with `algorithm: sha256` IS vaulted.
        self.assertIsInstance(creds["nested"]["inner"], VaultScalar)


if __name__ == "__main__":
    unittest.main()
