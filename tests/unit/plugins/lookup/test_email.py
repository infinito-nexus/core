# nocheck: comments-valid  explanatory WHY-comments predate the stricter lint
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.email import LookupModule
from utils.cache import _reset_cache_for_tests
from utils.cache import base as cache_base
from utils.cache import users as cache_users
from utils.cache.yaml import dump_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES


def _write_role_config(base_dir: Path, role_name: str, payload: dict) -> None:
    config_path = base_dir / "roles" / role_name / ROLE_FILE_META_SERVICES
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(dump_yaml_str(payload), encoding="utf-8")


class TestEmailLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _reset_cache_for_tests()
        cls.addClassCleanup(_reset_cache_for_tests)

    def setUp(self) -> None:
        cache_base._reset()
        self.lookup = LookupModule()
        self.lookup._templar = None
        self._cwd = str(Path.cwd())
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmpdir.name)
        (self._tmp / "roles").mkdir(parents=True, exist_ok=True)
        os.chdir(self._tmp)
        self._tokens_store_patcher = patch.object(
            cache_users, "_load_store_users", return_value={}
        )
        self._tokens_store_patcher.start()

    def tearDown(self) -> None:
        self._tokens_store_patcher.stop()
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

    def test_host_is_localhost_when_not_external_under_tls(self) -> None:
        result = self.lookup.run(
            [],
            variables={"inventory_hostname": "host1", "TLS_ENABLED": True},
        )[0]
        self.assertEqual(result["host"], "localhost")
        self.assertFalse(result["auth"])
        self.assertFalse(result["tls"])

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
        # Per the file root of meta/services.yml IS the services map
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

    def test_sso_relay_provider_disables_auth_and_uses_port_25(self) -> None:
        # submission_via_relay + Keycloak deployed -> relay on 25, no auth, STARTTLS.
        _write_role_config(
            self._tmp,
            "web-app-mailprov",
            {"sso": {"oidc": {"submission_via_relay": True}}},
        )
        variables = {
            "MAIL_PROVIDER": "web-app-mailprov",
            "group_names": ["web-app-mailprov", "web-app-keycloak"],
            "groups": {"web-app-mailprov": ["host1"], "web-app-keycloak": ["host1"]},
            "TLS_ENABLED": True,
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            [], variables=variables, roles_dir=str(self._tmp / "roles")
        )[0]
        self.assertEqual(result["port"], 25)
        self.assertFalse(result["auth"])
        self.assertTrue(result["start_tls"])

    def test_sso_relay_inactive_without_keycloak(self) -> None:
        # Same provider, but Keycloak is not deployed: keep authenticated 465.
        _write_role_config(
            self._tmp,
            "web-app-mailprov",
            {"sso": {"oidc": {"submission_via_relay": True}}},
        )
        variables = {
            "MAIL_PROVIDER": "web-app-mailprov",
            "group_names": ["web-app-mailprov"],
            "groups": {"web-app-mailprov": ["host1"]},
            "TLS_ENABLED": True,
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            [], variables=variables, roles_dir=str(self._tmp / "roles")
        )[0]
        self.assertEqual(result["port"], 465)
        self.assertTrue(result["auth"])
        self.assertFalse(result["start_tls"])

    def test_sso_relay_inactive_when_sso_enabled_pinned_false(self) -> None:
        # A variant pins the provider's sso.enabled to a literal false while
        # submission_via_relay stays true (role default) and Keycloak is still
        # deployed: the provider keeps password auth, so no relay mode.
        _write_role_config(
            self._tmp,
            "web-app-mailprov",
            {"sso": {"enabled": False, "oidc": {"submission_via_relay": True}}},
        )
        variables = {
            "MAIL_PROVIDER": "web-app-mailprov",
            "group_names": ["web-app-mailprov", "web-app-keycloak"],
            "groups": {"web-app-mailprov": ["host1"], "web-app-keycloak": ["host1"]},
            "TLS_ENABLED": True,
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            [], variables=variables, roles_dir=str(self._tmp / "roles")
        )[0]
        self.assertEqual(result["port"], 465)
        self.assertTrue(result["auth"])
        self.assertFalse(result["start_tls"])

    def test_sso_relay_active_with_untemplated_enabled_gate(self) -> None:
        # The role default gates sso.enabled on group_names (raw Jinja here);
        # the guard must not treat the untemplated string as false.
        _write_role_config(
            self._tmp,
            "web-app-mailprov",
            {
                "sso": {
                    "enabled": "{{ 'web-app-keycloak' in group_names }}",
                    "oidc": {"submission_via_relay": True},
                }
            },
        )
        variables = {
            "MAIL_PROVIDER": "web-app-mailprov",
            "group_names": ["web-app-mailprov", "web-app-keycloak"],
            "groups": {"web-app-mailprov": ["host1"], "web-app-keycloak": ["host1"]},
            "TLS_ENABLED": True,
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            [], variables=variables, roles_dir=str(self._tmp / "roles")
        )[0]
        self.assertEqual(result["port"], 25)
        self.assertFalse(result["auth"])
        self.assertTrue(result["start_tls"])

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
