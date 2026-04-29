from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from ansible.errors import AnsibleError

from plugins.lookup.email import LookupModule
from utils.cache import _reset_cache_for_tests
from utils.cache import users as cache_users


def _write_role_config(base_dir: Path, role_name: str, payload: dict) -> None:
    config_path = base_dir / "roles" / role_name / "meta" / "services.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(payload), encoding="utf-8")


class TestEmailLookup(unittest.TestCase):
    def setUp(self) -> None:
        self.lookup = LookupModule()
        self.lookup._templar = None
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmpdir.name)
        (self._tmp / "roles").mkdir(parents=True, exist_ok=True)
        os.chdir(self._tmp)
        _reset_cache_for_tests()
        self._tokens_store_patcher = patch.object(
            cache_users, "_load_store_users", return_value={}
        )
        self._tokens_store_patcher.start()

    def tearDown(self) -> None:
        self._tokens_store_patcher.stop()
        _reset_cache_for_tests()
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_returns_plugin_defaults_when_no_vars(self) -> None:
        result = self.lookup.run([], variables={"inventory_hostname": "host1"})[0]
        self.assertTrue(result["enabled"])
        self.assertEqual(result["host"], "localhost")
        self.assertEqual(result["port"], 25)
        self.assertEqual(result["from"], "root@host1.localdomain")
        self.assertEqual(result["username"], "root@host1.localdomain")
        self.assertEqual(result["password"], "")
        self.assertFalse(result["tls"])
        self.assertFalse(result["auth"])
        self.assertTrue(result["smtp"])

    def test_keys_are_lowercased_without_prefix(self) -> None:
        result = self.lookup.run([], variables={})[0]
        for key in result:
            self.assertFalse(key.startswith("SYSTEM_EMAIL_"))
            self.assertEqual(key, key.lower())

    def test_group_var_overrides_plugin_default(self) -> None:
        variables = {
            "SYSTEM_EMAIL_HOST": "smtp.example.org",
            "SYSTEM_EMAIL_PORT": 465,
            "SYSTEM_EMAIL_TLS": True,
            "inventory_hostname": "host1",
        }
        result = self.lookup.run([], variables=variables)[0]
        self.assertEqual(result["host"], "smtp.example.org")
        self.assertEqual(result["port"], 465)
        self.assertTrue(result["tls"])
        self.assertEqual(result["from"], "root@host1.localdomain")

    def test_empty_string_falls_back_to_plugin_default(self) -> None:
        variables = {
            "SYSTEM_EMAIL_HOST": "",
            "inventory_hostname": "host1",
        }
        result = self.lookup.run([], variables=variables)[0]
        self.assertEqual(result["host"], "localhost")

    def test_application_override_wins_over_defaults(self) -> None:
        # Per req-008 the file root of meta/services.yml IS the services map
        # (no `compose.services` envelope).
        _write_role_config(
            self._tmp,
            "web-app-x",
            {"email": {"host": "smtp.app.org", "port": 587}},
        )
        variables = {
            "SYSTEM_EMAIL_HOST": "smtp.global.org",
            "SYSTEM_EMAIL_PORT": 25,
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            ["web-app-x"],
            variables=variables,
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result["host"], "smtp.app.org")
        self.assertEqual(result["port"], 587)
        self.assertEqual(result["from"], "root@host1.localdomain")

    def test_missing_application_returns_defaults(self) -> None:
        variables = {
            "SYSTEM_EMAIL_HOST": "smtp.global.org",
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            ["web-app-unknown"],
            variables=variables,
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result["host"], "smtp.global.org")

    def test_application_without_email_service_returns_defaults(self) -> None:
        _write_role_config(
            self._tmp,
            "web-app-nomail",
            {"logout": {"enabled": True}},
        )
        variables = {
            "SYSTEM_EMAIL_HOST": "smtp.global.org",
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            ["web-app-nomail"],
            variables=variables,
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result["host"], "smtp.global.org")

    def test_too_many_terms_raises(self) -> None:
        with self.assertRaises(AnsibleError):
            self.lookup.run(["a", "b"], variables={})

    def test_computed_defaults_are_templated(self) -> None:
        self.lookup._templar = _DummyTemplar(
            {"DOMAIN_PRIMARY_RESOLVED": "mail.example.org"}
        )
        variables = {
            "DOMAIN_PRIMARY": "{{ DOMAIN_PRIMARY_RESOLVED }}",
            "inventory_hostname": "host1",
        }
        result = self.lookup.run([], variables=variables)[0]
        self.assertEqual(result["domain"], "mail.example.org")


class _DummyTemplar:
    def __init__(self, available_variables: dict[str, str]) -> None:
        self.available_variables = available_variables

    def template(self, value, fail_on_undefined=False):
        if isinstance(value, str):
            rendered = value
            for key, replacement in self.available_variables.items():
                rendered = rendered.replace(f"{{{{ {key} }}}}", str(replacement))
            return rendered
        return value


if __name__ == "__main__":
    unittest.main()
