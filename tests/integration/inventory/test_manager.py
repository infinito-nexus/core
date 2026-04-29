import tempfile
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

from utils.manager.inventory import InventoryManager  # type: ignore
from utils.handler.vault import VaultScalar  # type: ignore


class _FakeVaultHandler:
    """
    Fake VaultHandler for integration tests.
    Avoids calling ansible-vault / subprocess, but still returns a vault-like snippet
    that InventoryManager can parse into a VaultScalar body.
    """

    def __init__(self, vault_pw: str) -> None:
        self.vault_pw = vault_pw
        self.calls: list[tuple[str, str]] = []

    def encrypt_string(self, plaintext: str, key_name: str) -> str:
        self.calls.append((plaintext, key_name))

        # This format must have at least 2 lines after splitlines(),
        # because InventoryManager reads lines[1] for indent detection.
        return (
            f"!vault |\n  $ANSIBLE_VAULT;1.1;AES256\n    PLAIN:{key_name}:{plaintext}\n"
        )


class TestInventoryManagerIntegration(TestCase):
    def test_apply_schema_with_transitive_provider_role_resolution(self):
        """
        Integration-style test (REAL provider resolution):
        - Writes real YAML files to disk for:
            - root role: roles/web-app-demo
            - provider role: roles/svc-db-mariadb
        - Uses real YamlHandler parsing
        - Patches only VaultHandler to avoid external ansible-vault calls
        - Verifies:
            - root role generates plain feature-based credentials
            - schema credentials are vaulted
            - provider role credentials are vaulted transitively
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            roles_root = tmp / "roles"
            roles_root.mkdir(parents=True, exist_ok=True)

            # ------------------------------------------------------------------
            # Provider role: roles/svc-db-mariadb
            # ------------------------------------------------------------------
            provider_role = roles_root / "svc-db-mariadb"
            (provider_role / "meta").mkdir(parents=True, exist_ok=True)
            (provider_role / "vars").mkdir(parents=True, exist_ok=True)
            (provider_role / "config").mkdir(parents=True, exist_ok=True)

            (provider_role / "vars" / "main.yml").write_text(
                'application_id: "svc-db-mariadb"\n',
                encoding="utf-8",
            )

            (provider_role / "meta" / "services.yml").write_text(
                "mariadb:\n  enabled: false\n  shared: true\n",
                encoding="utf-8",
            )

            (provider_role / "meta" / "schema.yml").write_text(
                "credentials:\n"
                "  root_password:\n"
                "    description: MariaDB root password\n"
                "    algorithm: random_hex_16\n"
                "    validation: {}\n"
                "  replication_password:\n"
                "    description: MariaDB replication password\n"
                "    algorithm: random_hex_16\n"
                "    validation: {}\n",
                encoding="utf-8",
            )

            # ------------------------------------------------------------------
            # Root role: roles/web-app-demo
            # ------------------------------------------------------------------
            role_path = roles_root / "web-app-demo"
            (role_path / "meta").mkdir(parents=True, exist_ok=True)
            (role_path / "vars").mkdir(parents=True, exist_ok=True)
            (role_path / "config").mkdir(parents=True, exist_ok=True)

            inv_path = tmp / "inventory.yml"
            inv_path.write_text("applications: {}\n", encoding="utf-8")

            (role_path / "vars" / "main.yml").write_text(
                'application_id: "web-app-demo"\n',
                encoding="utf-8",
            )

            (role_path / "meta" / "services.yml").write_text(
                "mariadb:\n  enabled: true\n  shared: true\noidc:\n  enabled: true\n",
                encoding="utf-8",
            )

            (role_path / "meta" / "schema.yml").write_text(
                "credentials:\n"
                "  api_key:\n"
                "    description: API key\n"
                "    algorithm: random_hex_16\n"
                "    validation: {}\n"
                "  plain_needed:\n"
                "    description: Needs override\n"
                "    algorithm: plain\n"
                "    validation: {}\n"
                "non_credentials:\n"
                "  flag: true\n",
                encoding="utf-8",
            )

            fake_vault = _FakeVaultHandler("pw")

            with patch(
                "utils.manager.inventory.VaultHandler",
                side_effect=lambda pw: fake_vault,
            ):
                mgr = InventoryManager(
                    role_path=role_path,
                    inventory_path=inv_path,
                    vault_pw="pw",
                    overrides={"credentials.plain_needed": "OVERRIDE"},
                    allow_empty_plain=False,
                )
                inv = mgr.apply_schema()

            apps = inv.get("applications", {})
            self.assertIn("web-app-demo", apps)
            self.assertIn("svc-db-mariadb", apps)

            # ------------------------------------------------------------------
            # Root app assertions
            # ------------------------------------------------------------------
            root_app = apps["web-app-demo"]
            root_creds = root_app["credentials"]

            self.assertIn("database_password", root_creds)
            self.assertIsInstance(root_creds["database_password"], str)
            self.assertNotIsInstance(root_creds["database_password"], VaultScalar)

            self.assertIn("oauth2_proxy_cookie_secret", root_creds)
            self.assertIsInstance(root_creds["oauth2_proxy_cookie_secret"], str)
            self.assertNotIsInstance(
                root_creds["oauth2_proxy_cookie_secret"], VaultScalar
            )

            self.assertIn("api_key", root_creds)
            self.assertIsInstance(root_creds["api_key"], VaultScalar)
            self.assertIn("$ANSIBLE_VAULT", str(root_creds["api_key"]))

            self.assertIn("plain_needed", root_creds)
            self.assertIsInstance(root_creds["plain_needed"], VaultScalar)
            self.assertIn(
                "PLAIN:plain_needed:OVERRIDE", str(root_creds["plain_needed"])
            )

            self.assertEqual(root_app["non_credentials"]["flag"], True)

            # ------------------------------------------------------------------
            # Provider app assertions
            # ------------------------------------------------------------------
            prov_app = apps["svc-db-mariadb"]
            prov_creds = prov_app["credentials"]

            self.assertIn("root_password", prov_creds)
            self.assertIsInstance(prov_creds["root_password"], VaultScalar)

            self.assertIn("replication_password", prov_creds)
            self.assertIsInstance(prov_creds["replication_password"], VaultScalar)

            # ------------------------------------------------------------------
            # Vault calls verification
            # ------------------------------------------------------------------
            called_keys = [k for (_plain, k) in fake_vault.calls]

            self.assertIn("api_key", called_keys)
            self.assertIn("plain_needed", called_keys)
            self.assertIn("root_password", called_keys)
            self.assertIn("replication_password", called_keys)

            self.assertNotIn("database_password", called_keys)
            self.assertNotIn("oauth2_proxy_cookie_secret", called_keys)

    def test_apply_schema_skips_schema_less_transitive_provider_role(self):
        """
        Shared provider roles without schema/main.yml must be ignored gracefully.
        This matters for roles like web-svc-asset that participate in dependency
        discovery but do not define credentials.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            roles_root = tmp / "roles"
            roles_root.mkdir(parents=True, exist_ok=True)

            provider_role = roles_root / "web-svc-asset"
            (provider_role / "meta").mkdir(parents=True, exist_ok=True)
            (provider_role / "vars").mkdir(parents=True, exist_ok=True)
            (provider_role / "config").mkdir(parents=True, exist_ok=True)

            (provider_role / "vars" / "main.yml").write_text(
                'application_id: "web-svc-asset"\n',
                encoding="utf-8",
            )
            (provider_role / "meta" / "services.yml").write_text(
                "asset:\n  enabled: false\n  shared: true\n",
                encoding="utf-8",
            )

            role_path = roles_root / "web-app-demo"
            (role_path / "meta").mkdir(parents=True, exist_ok=True)
            (role_path / "vars").mkdir(parents=True, exist_ok=True)
            (role_path / "config").mkdir(parents=True, exist_ok=True)

            inv_path = tmp / "inventory.yml"
            inv_path.write_text("applications: {}\n", encoding="utf-8")

            (role_path / "vars" / "main.yml").write_text(
                'application_id: "web-app-demo"\n',
                encoding="utf-8",
            )
            (role_path / "meta" / "services.yml").write_text(
                "asset:\n  enabled: true\n  shared: true\n",
                encoding="utf-8",
            )
            (role_path / "meta" / "schema.yml").write_text(
                "credentials:\n"
                "  api_key:\n"
                "    description: API key\n"
                "    algorithm: random_hex_16\n"
                "    validation: {}\n",
                encoding="utf-8",
            )

            fake_vault = _FakeVaultHandler("pw")
            with patch(
                "utils.manager.inventory.VaultHandler",
                side_effect=lambda pw: fake_vault,
            ):
                mgr = InventoryManager(
                    role_path=role_path,
                    inventory_path=inv_path,
                    vault_pw="pw",
                    overrides={},
                    allow_empty_plain=False,
                )
                inv = mgr.apply_schema()

            apps = inv.get("applications", {})
            self.assertIn("web-app-demo", apps)
            self.assertIn("api_key", apps["web-app-demo"]["credentials"])
            self.assertNotIn("web-svc-asset", apps)


if __name__ == "__main__":
    main()
