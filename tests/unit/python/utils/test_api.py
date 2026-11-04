import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.api import declared_api, provider_enabled, resolve_api


class TestResolveApi(unittest.TestCase):
    def test_playbook_group_vars_preserve_inventory_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory)
            (inventory / "hosts.yml").write_text(
                "all:\n  hosts:\n    api-test-host: {}\n"
            )
            (inventory / "group_vars").mkdir()
            (inventory / "group_vars/all.yml").write_text(
                "API:\n  anthropic:\n    api_key: inventory-test-key\n"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ansible.cli.inventory",
                    "-i",
                    str(inventory / "hosts.yml"),
                    "--playbook-dir",
                    str(PROJECT_ROOT),
                    "--host",
                    "api-test-host",
                ],
                capture_output=True,
                text=True,
                check=True,
                env=dict(os.environ, ANSIBLE_LOCAL_TEMP=directory),
            )
            variables = json.loads(result.stdout)
            resolved = resolve_api(variables)
            self.assertEqual(resolved["anthropic"]["api_key"], "inventory-test-key")
            self.assertIn("github", resolved)

    def test_a_partial_override_keeps_the_declared_providers(self) -> None:
        declared = declared_api()
        self.assertIn("github", declared)

        resolved = resolve_api({"API": {"openai": {"api_key": "sk-test"}}})

        self.assertEqual(set(resolved), set(declared))
        self.assertEqual(resolved["openai"]["api_key"], "sk-test")
        self.assertEqual(resolved["github"]["client_id"], "")

    def test_an_override_wins_per_key(self) -> None:
        resolved = resolve_api({"API": {"github": {"client_id": "ID42"}}})

        self.assertEqual(resolved["github"]["client_id"], "ID42")
        self.assertEqual(resolved["github"]["client_secret"], "")

    def test_a_missing_api_falls_back_to_the_declaration(self) -> None:
        self.assertEqual(resolve_api({}), declared_api())

    def test_a_non_mapping_api_is_an_error(self) -> None:
        with self.assertRaises(TypeError):
            resolve_api({"API": "nope"})


class TestProviderEnabled(unittest.TestCase):
    def test_every_credential_must_carry_a_value(self) -> None:
        api = {"github": {"client_id": "ID42", "client_secret": "SEC42"}}

        self.assertTrue(provider_enabled(api, "github"))

    def test_one_empty_credential_disables_the_provider(self) -> None:
        api = {"github": {"client_id": "ID42", "client_secret": "   "}}

        self.assertFalse(provider_enabled(api, "github"))

    def test_a_provider_without_credentials_is_disabled(self) -> None:
        self.assertFalse(provider_enabled({"github": {}}, "github"))

    def test_an_undeclared_provider_is_an_error(self) -> None:
        with self.assertRaises(KeyError):
            provider_enabled({}, "github")


if __name__ == "__main__":
    unittest.main()
