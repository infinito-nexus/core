# tests/unit/python/plugins/lookup/test_config_lookup_unittest.py
from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.lookup.config import LookupModule
from utils.cache import applications as cache_applications
from utils.cache import base as cache_base
from utils.cache import carrier as cache_carrier
from utils.cache import domains as cache_domains
from utils.cache import users as cache_users
from utils.cache.reset import _reset_cache_for_tests
from utils.cache.yaml import dump_yaml_str
from utils.roles.applications.config import AppConfigKeyError, ConfigEntryNotSetError
from utils.roles.mapping import (
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_USERS,
)


def _write_schema(base_dir: Path, application_id: str, schema: dict) -> None:
    schema_path = base_dir / "roles" / application_id / ROLE_FILE_META_SECRETS
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(dump_yaml_str(schema), encoding="utf-8")


def _write_config(base_dir: Path, application_id: str, config: dict) -> None:
    config_path = base_dir / "roles" / application_id / ROLE_FILE_META_SERVICES
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(dump_yaml_str(config), encoding="utf-8")


def _write_users(base_dir: Path, application_id: str, users: dict) -> None:
    """Write meta/users.yml — file root IS the users map."""
    users_path = base_dir / "roles" / application_id / ROLE_FILE_META_USERS
    users_path.parent.mkdir(parents=True, exist_ok=True)
    users_path.write_text(dump_yaml_str(users), encoding="utf-8")


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
    @classmethod
    def setUpClass(cls) -> None:
        _reset_cache_for_tests()
        cls.addClassCleanup(_reset_cache_for_tests)

    def setUp(self) -> None:
        cache_base._reset()
        self.lm = LookupModule()
        self._cwd = str(Path.cwd())
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmpdir.name)
        os.chdir(self._tmp)

    def tearDown(self) -> None:
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
            {"smtp": {"host": {}, "port": {}}},
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


class TestConfigLookupKeysOnGroupNames(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()
        self.addCleanup(_reset_cache_for_tests)
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self._roles = Path(tmpdir.name) / "roles"
        _write_config(
            Path(tmpdir.name),
            "web-app-foo",
            {"logout": {"enabled": "{{ 'web-svc-logout' in group_names }}"}},
        )

    def _variables(self, *groups: str) -> dict:
        return {
            "DOMAIN_PRIMARY": "example.org",
            "group_names": ["web-app-foo", *groups],
        }

    def _enabled(self, *groups: str) -> object:
        lookup = LookupModule()
        lookup._templar = Templar(loader=DataLoader())
        return lookup.run(
            ["web-app-foo", "services.logout.enabled"],
            variables=self._variables(*groups),
            roles_dir=str(self._roles),
        )[0]

    def _member_then_outsider(self) -> tuple[object, object]:
        return self._enabled("web-svc-logout"), self._enabled()

    def test_a_host_outside_the_group_does_not_read_a_member_payload(self) -> None:
        self.assertEqual(self._member_then_outsider(), (True, False))

    def test_a_key_without_group_names_serves_the_member_payload(self) -> None:
        signature = cache_base._stable_variables_signature

        def without_group_names(variables):
            return signature(variables)[:4]

        with (
            unittest.mock.patch.object(
                cache_carrier, "_stable_variables_signature", without_group_names
            ),
            unittest.mock.patch.object(
                cache_domains, "_stable_variables_signature", without_group_names
            ),
            unittest.mock.patch.object(
                cache_users, "_stable_variables_signature", without_group_names
            ),
        ):
            self.assertEqual(self._member_then_outsider(), (True, True))

    def test_identical_scopes_render_once(self) -> None:
        templar = Templar(loader=DataLoader())
        first, second = (
            cache_applications.get_merged_applications(
                variables=self._variables(), roles_dir=self._roles, templar=templar
            )
            for _ in range(2)
        )
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
