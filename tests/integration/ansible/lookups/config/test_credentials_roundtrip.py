"""The credential seam: what the generator writes is what a role reads back.

``meta/secrets.yml`` is produced by one component and consumed by another.
:class:`~utils.manager.inventory.InventoryManager` materialises the values into
``applications.<app>.secrets.credentials``; every role then reads them through
``lookup('config', <app>, 'secrets.credentials.<key>')``. Nothing checked that
the two agree on where the values live, which is exactly what the rename from
``meta/schema.yml`` put at risk.

The second test guards the caching side of that seam: the assembled defaults
must not reach into the YAML cache and truncate the schema every later reader
shares.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.applications import get_application_defaults
from utils.cache.yaml import load_yaml_any
from utils.manager.credential_key import CREDENTIALS_KEY, SECRETS_KEY, override_key
from utils.manager.inventory import InventoryManager
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_VARS_MAIN

APP_ID = "web-app-roundtrip"
SECRETS = """\
credentials:
  api_token:
    description: token
    algorithm: sha256
    validation: ^[a-f0-9]{64}$
  nested:
    inner:
      description: inner
      algorithm: alphanumeric
      validation: ^.*$
  plain_token:
    description: operator supplied
    algorithm: plain
    validation: ^.*$
"""


class TestCredentialRoundTrip(unittest.TestCase):
    def _generate(self, overrides=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        role = root / "roles" / APP_ID
        (role / "meta").mkdir(parents=True)
        (role / "vars").mkdir()
        (role / ROLE_FILE_META_SECRETS).write_text(SECRETS)
        (role / ROLE_FILE_VARS_MAIN).write_text(f"application_id: {APP_ID}\n")

        inventory = root / "host_vars.yml"
        inventory.write_text("{}\n")
        vault_pw = root / "vault.txt"
        vault_pw.write_text("pw\n")

        manager = InventoryManager(
            role_path=role,
            inventory_path=inventory,
            vault_pw=str(vault_pw),
            overrides=overrides or {},
        )
        return manager.apply_schema()["applications"][APP_ID]

    def test_the_generator_writes_under_the_secrets_root(self) -> None:
        block = self._generate(overrides={override_key(APP_ID, "plain_token"): "x"})
        self.assertIn(SECRETS_KEY, block)
        self.assertIn(CREDENTIALS_KEY, block[SECRETS_KEY])
        self.assertIn("api_token", block[SECRETS_KEY][CREDENTIALS_KEY])

    def test_nested_credentials_keep_their_shape(self) -> None:
        block = self._generate(overrides={override_key(APP_ID, "plain_token"): "x"})
        nested = block[SECRETS_KEY][CREDENTIALS_KEY]["nested"]
        self.assertIn("inner", nested)

    def test_the_override_key_the_cli_builds_is_the_one_the_manager_reads(self) -> None:
        """A plain credential has no generator, so the manager demands an
        override and names the key it expects — the same one the CLI parses.
        Supplying exactly that key satisfies it; the stored value is vaulted,
        so the key identity is what can be observed, not the plaintext."""
        key = override_key(APP_ID, "plain_token")
        with self.assertRaises(SystemExit):
            self._generate()
        block = self._generate(overrides={key: "chosen"})
        self.assertIn("plain_token", block[SECRETS_KEY][CREDENTIALS_KEY])

    def test_nothing_reads_the_pre_rename_root(self) -> None:
        block = self._generate(overrides={override_key(APP_ID, "plain_token"): "x"})
        self.assertNotIn(CREDENTIALS_KEY, block)


class TestSchemaCacheIsNotTruncated(unittest.TestCase):
    """Assembling the defaults must leave the shared YAML cache untouched.

    ``meta/secrets.yml`` is not a generic meta topic: only its ``default:``
    bearing leaves belong in the resolved config. Letting the generic file-root
    loop assign it first made the follow-up write land inside the cached
    document, so every later reader saw a schema with most credentials gone.
    """

    def test_the_cached_schema_survives_the_defaults_pass(self) -> None:
        path = PROJECT_ROOT / "roles" / "web-app-keycloak" / ROLE_FILE_META_SECRETS
        before = sorted(
            (load_yaml_any(path, default_if_missing={}) or {}).get(CREDENTIALS_KEY, {})
        )
        get_application_defaults(roles_dir=PROJECT_ROOT / "roles")
        after = sorted(
            (load_yaml_any(path, default_if_missing={}) or {}).get(CREDENTIALS_KEY, {})
        )
        self.assertEqual(before, after)
        self.assertIn("administrator_password", after)


if __name__ == "__main__":
    unittest.main()
