# tests/unit/plugins/lookup/test_config_lookup_unittest.py
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.errors import AnsibleError

from plugins.lookup.config import LookupModule
from utils.applications.config import AppConfigKeyError, ConfigEntryNotSetError
from utils.cache import _reset_cache_for_tests


def _write_schema(base_dir: Path, application_id: str, schema: dict) -> None:
    schema_path = base_dir / "roles" / application_id / "meta" / "schema.yml"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(yaml.safe_dump(schema), encoding="utf-8")


def _write_config(base_dir: Path, application_id: str, config: dict) -> None:
    config_path = base_dir / "roles" / application_id / "meta" / "services.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")


def _write_users(base_dir: Path, application_id: str, users: dict) -> None:
    """Write meta/users.yml — file root IS the users map (req-008)."""
    users_path = base_dir / "roles" / application_id / "meta" / "users.yml"
    users_path.parent.mkdir(parents=True, exist_ok=True)
    users_path.write_text(yaml.safe_dump(users), encoding="utf-8")


class _DummyTemplar:
    def __init__(self, available_variables: dict[str, str]) -> None:
        self.available_variables = available_variables

    def template(self, value, fail_on_undefined=False):
        if isinstance(value, str):
            rendered = value
            for key, replacement in self.available_variables.items():
                rendered = rendered.replace(f"{{{{ {key} }}}}", str(replacement))
            return rendered
        if isinstance(value, dict):
            return {
                key: self.template(item, fail_on_undefined=fail_on_undefined)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self.template(item, fail_on_undefined=fail_on_undefined)
                for item in value
            ]
        return value


class TestConfigLookup(unittest.TestCase):
    def setUp(self) -> None:
        self.lm = LookupModule()
        _reset_cache_for_tests()

        # Create a temp working directory in /tmp and chdir into it
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmpdir.name)
        os.chdir(self._tmp)

    def tearDown(self) -> None:
        _reset_cache_for_tests()
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_requires_2_or_3_terms(self) -> None:
        with self.assertRaises(AnsibleError):
            self.lm.run([], variables={"applications": {}})
        with self.assertRaises(AnsibleError):
            self.lm.run(["a"], variables={"applications": {}})
        with self.assertRaises(AnsibleError):
            self.lm.run(["a", "b", "c", "d"], variables={"applications": {}})

    def test_resolves_from_roles_without_applications_var(self) -> None:
        # meta/services.yml file root IS the services map (req-008): the
        # consumer path therefore reads `services.<entity>.<…>`.
        _write_config(
            self._tmp,
            "web-app-foo",
            {"smtp": {"host": "mail.example.org"}},
        )
        out = self.lm.run(
            ["web-app-foo", "services.smtp.host"],
            variables={},
            roles_dir=str(self._tmp / "roles"),
        )
        self.assertEqual(out, ["mail.example.org"])

    def test_renders_selected_value_with_templar_variables(self) -> None:
        _write_config(
            self._tmp,
            "web-app-foo",
            {"foo": {"domain": "{{ SYSTEM_EMAIL_DOMAIN }}"}},
        )
        self.lm._templar = _DummyTemplar({"SYSTEM_EMAIL_DOMAIN": "mail.example.org"})
        out = self.lm.run(
            ["web-app-foo", "services.foo.domain"],
            variables={"SYSTEM_EMAIL_DOMAIN": "mail.example.org"},
            roles_dir=str(self._tmp / "roles"),
        )
        self.assertEqual(out, ["mail.example.org"])

    def test_users_path_returns_rendered_user_value(self) -> None:
        _write_config(self._tmp, "web-app-foo", {"foo": {"enabled": True}})
        _write_users(self._tmp, "web-app-foo", {"administrator": {}})
        self.lm._templar = _DummyTemplar({"DOMAIN_PRIMARY": "mail.example.org"})
        out = self.lm.run(
            ["web-app-foo", "users.administrator.email"],
            variables={"DOMAIN_PRIMARY": "mail.example.org"},
            roles_dir=str(self._tmp / "roles"),
        )
        self.assertEqual(out, ["administrator@mail.example.org"])

    def test_requires_applications_var_is_dict(self) -> None:
        with self.assertRaises(AnsibleError):
            self.lm.run(
                ["app", "x.y"], variables={"applications": ["not", "a", "dict"]}
            )

    def test_returns_value_when_present(self) -> None:
        variables = {
            "applications": {"web-app-foo": {"smtp": {"host": "mail.example.org"}}}
        }
        out = self.lm.run(["web-app-foo", "smtp.host"], variables=variables)
        self.assertEqual(out, ["mail.example.org"])

    def test_strict_missing_key_raises_appconfigkeyerror(self) -> None:
        variables = {
            "applications": {"web-app-foo": {"smtp": {"host": "mail.example.org"}}}
        }
        with self.assertRaises(AppConfigKeyError):
            self.lm.run(["web-app-foo", "smtp.port"], variables=variables)

    def test_default_third_arg_disables_strict_and_returns_default(self) -> None:
        variables = {
            "applications": {"web-app-foo": {"smtp": {"host": "mail.example.org"}}}
        }
        out = self.lm.run(["web-app-foo", "smtp.port", 25], variables=variables)
        self.assertEqual(out, [25])

    def test_strict_missing_app_id_raises(self) -> None:
        variables = {
            "applications": {"web-app-foo": {"smtp": {"host": "mail.example.org"}}}
        }
        with self.assertRaises(AppConfigKeyError):
            self.lm.run(["web-app-missing", "smtp.host"], variables=variables)

    def test_schema_defined_but_unset_raises_configentrynotseterror(self) -> None:
        _write_schema(
            self._tmp,
            "web-app-foo",
            {"smtp": {"host": {}, "port": {}}},  # port is defined in schema
        )
        variables = {
            "applications": {"web-app-foo": {"smtp": {"host": "mail.example.org"}}}
        }
        with self.assertRaises(ConfigEntryNotSetError):
            self.lm.run(["web-app-foo", "smtp.port"], variables=variables)

    def test_index_access_supported(self) -> None:
        variables = {
            "applications": {
                "web-app-foo": {"hosts": ["a.example.org", "b.example.org"]}
            }
        }
        out = self.lm.run(["web-app-foo", "hosts[1]"], variables=variables)
        self.assertEqual(out, ["b.example.org"])

    def test_index_out_of_range_strict_raises(self) -> None:
        variables = {"applications": {"web-app-foo": {"hosts": ["a.example.org"]}}}
        with self.assertRaises(AppConfigKeyError):
            self.lm.run(["web-app-foo", "hosts[5]"], variables=variables)

    def test_index_out_of_range_with_default_returns_default(self) -> None:
        variables = {"applications": {"web-app-foo": {"hosts": ["a.example.org"]}}}
        out = self.lm.run(["web-app-foo", "hosts[5]", "fallback"], variables=variables)
        self.assertEqual(out, ["fallback"])


if __name__ == "__main__":
    unittest.main()
