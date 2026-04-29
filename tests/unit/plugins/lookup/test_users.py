from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from ansible.errors import AnsibleError

from plugins.lookup.users import LookupModule, _reset_cache_for_tests
from utils.cache import base as runtime_data_base


def _write_users(base_dir: Path, role_name: str, users: dict) -> None:
    """Write meta/users.yml — file root IS the users map (req-008)."""
    users_path = base_dir / "roles" / role_name / "meta" / "users.yml"
    users_path.parent.mkdir(parents=True, exist_ok=True)
    users_path.write_text(yaml.safe_dump(users), encoding="utf-8")


class TestUsersLookup(unittest.TestCase):
    def setUp(self) -> None:
        self.lookup = LookupModule()
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmpdir.name)
        os.chdir(self._tmp)
        _reset_cache_for_tests()

        _write_users(
            self._tmp,
            "identity",
            {
                "alice": {
                    "username": "alice",
                    "email": "alice@example.org",
                    "authorized_keys": ["ssh-ed25519 AAAA alice@example.org"],
                }
            },
        )
        self.lookup._templar = None

    def tearDown(self) -> None:
        _reset_cache_for_tests()
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_returns_full_mapping(self) -> None:
        result = self.lookup.run([], variables={}, roles_dir=str(self._tmp / "roles"))[
            0
        ]
        self.assertIn("alice", result)
        self.assertEqual(result["alice"]["email"], "alice@example.org")

    def test_returns_single_entry(self) -> None:
        result = self.lookup.run(
            ["alice"],
            variables={},
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result["username"], "alice")

    def test_applies_inventory_override(self) -> None:
        result = self.lookup.run(
            ["alice"],
            variables={"users": {"alice": {"email": "override@example.org"}}},
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result["email"], "override@example.org")
        self.assertEqual(result["username"], "alice")

    def test_ignores_non_mapping_runtime_users_placeholder(self) -> None:
        result = self.lookup.run(
            ["alice"],
            variables={"users": "alice"},
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result["email"], "alice@example.org")
        self.assertEqual(result["username"], "alice")

    def test_missing_entry_raises_without_default(self) -> None:
        with self.assertRaises(AnsibleError):
            self.lookup.run(
                ["bob"],
                variables={},
                roles_dir=str(self._tmp / "roles"),
            )

    def test_missing_entry_returns_default_when_provided(self) -> None:
        default_value = {"fallback": True}
        result = self.lookup.run(
            ["bob", default_value],
            variables={},
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result, default_value)

    def test_renders_templated_defaults_with_templar(self) -> None:
        _write_users(
            self._tmp,
            "templated",
            {
                "blackhole": {
                    "email": "blackhole@{{ SYSTEM_EMAIL_DOMAIN }}",
                    "password": "{{ 42 | strong_password }}",
                }
            },
        )
        _reset_cache_for_tests()
        self.lookup._templar = _SplitTemplar(
            {"SYSTEM_EMAIL_DOMAIN": "mail.example.org"}
        )

        result = self.lookup.run(
            ["blackhole"],
            variables={"SYSTEM_EMAIL_DOMAIN": "mail.example.org"},
            roles_dir=str(self._tmp / "roles"),
        )[0]

        self.assertEqual(result["email"], "blackhole@mail.example.org")
        self.assertEqual(result["password"], "strong-password-42")

    def test_domain_primary_falls_back_to_system_email_domain(self) -> None:
        _write_users(
            self._tmp,
            "templated",
            {
                "sld": {
                    "username": "{{ DOMAIN_PRIMARY.split('.')[0] }}",
                    "reserved": True,
                }
            },
        )
        _reset_cache_for_tests()
        self.lookup._templar = _SplitTemplar(
            {"SYSTEM_EMAIL_DOMAIN": "mail.example.org"}
        )

        result = self.lookup.run(
            ["sld"],
            variables={"SYSTEM_EMAIL_DOMAIN": "mail.example.org"},
            roles_dir=str(self._tmp / "roles"),
        )[0]

        self.assertEqual(result["username"], "mail")

    def test_materializes_sld_without_templar_when_domain_primary_is_available(
        self,
    ) -> None:
        _write_users(
            self._tmp,
            "templated",
            {
                "sld": {
                    "username": "{{ DOMAIN_PRIMARY.split('.')[0] }}",
                    "reserved": True,
                }
            },
        )
        _reset_cache_for_tests()
        self.lookup._templar = None

        result = self.lookup.run(
            ["sld"],
            variables={"DOMAIN_PRIMARY": "portal.example.org"},
            roles_dir=str(self._tmp / "roles"),
        )[0]

        self.assertEqual(result["username"], "portal")

    def test_materializes_sld_from_role_domain_when_global_domain_is_missing(
        self,
    ) -> None:
        _write_users(
            self._tmp,
            "templated",
            {
                "sld": {
                    "username": "{{ DOMAIN_PRIMARY.split('.')[0] }}",
                    "reserved": True,
                }
            },
        )
        _reset_cache_for_tests()
        self.lookup._templar = None

        result = self.lookup.run(
            ["sld"],
            variables={"domain": "auth.infinito.example"},
            roles_dir=str(self._tmp / "roles"),
        )[0]

        self.assertEqual(result["username"], "infinito")

    def test_materializes_sld_from_env_backed_domain_primary(self) -> None:
        _write_users(
            self._tmp,
            "templated",
            {
                "sld": {
                    "username": "{{ DOMAIN_PRIMARY.split('.')[0] }}",
                    "reserved": True,
                }
            },
        )
        _reset_cache_for_tests()
        self.lookup._templar = None

        with patch.dict(os.environ, {"DOMAIN": "infinito.localhost"}, clear=False):
            result = self.lookup.run(
                ["sld"],
                variables={
                    "DOMAIN_PRIMARY": "{{ lookup('env', 'DOMAIN') | default('infinito.localhost', true) }}"
                },
                roles_dir=str(self._tmp / "roles"),
            )[0]

        self.assertEqual(result["username"], "infinito")

    def test_renders_templated_defaults_when_templar_returns_unchanged(self) -> None:
        _write_users(
            self._tmp,
            "templated",
            {
                "blackhole": {
                    "email": "blackhole@{{ SYSTEM_EMAIL_DOMAIN }}",
                    "password": "{{ 16 | strong_password }}",
                }
            },
        )
        _reset_cache_for_tests()
        self.lookup._templar = _NoopTemplar({"SYSTEM_EMAIL_DOMAIN": "mail.example.org"})

        result = self.lookup.run(
            ["blackhole"],
            variables={"SYSTEM_EMAIL_DOMAIN": "mail.example.org"},
            roles_dir=str(self._tmp / "roles"),
        )[0]

        self.assertEqual(result["email"], "blackhole@mail.example.org")
        self.assertNotIn("{{", result["password"])
        self.assertGreaterEqual(len(result["password"]), 12)

    def test_hydrates_tokens_from_dir_secrets_when_file_tokens_missing(self) -> None:
        secrets_dir = self._tmp / "var" / "lib" / "infinito" / "secrets"
        secrets_dir.mkdir(parents=True, exist_ok=True)
        (secrets_dir / "tokens.yml").write_text(
            yaml.safe_dump(
                {
                    "users": {
                        "alice": {
                            "tokens": {
                                "web-app-mailu": "token-from-dir-secrets",
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        result = self.lookup.run(
            ["alice"],
            variables={"DIR_SECRETS": str(secrets_dir)},
            roles_dir=str(self._tmp / "roles"),
        )[0]

        self.assertEqual(result["tokens"]["web-app-mailu"], "token-from-dir-secrets")

    def test_hydrates_tokens_from_default_store_path_when_path_vars_missing(
        self,
    ) -> None:
        default_tokens = self._tmp / "default" / "tokens.yml"
        default_tokens.parent.mkdir(parents=True, exist_ok=True)
        default_tokens.write_text(
            yaml.safe_dump(
                {
                    "users": {
                        "alice": {
                            "tokens": {
                                "web-app-mailu": "token-from-default-path",
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        # Patch the actual constant in `utils.cache.base` —
        # `_resolve_tokens_file` reads it from there at call time.
        previous_default = runtime_data_base.DEFAULT_TOKENS_FILE
        runtime_data_base.DEFAULT_TOKENS_FILE = default_tokens
        try:
            result = self.lookup.run(
                ["alice"],
                variables={},
                roles_dir=str(self._tmp / "roles"),
            )[0]
        finally:
            runtime_data_base.DEFAULT_TOKENS_FILE = previous_default

        self.assertEqual(result["tokens"]["web-app-mailu"], "token-from-default-path")


class _DummyTemplar:
    def __init__(self, variables: dict[str, str]) -> None:
        self.available_variables = dict(variables)

    def template(self, value, fail_on_undefined=False):
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
        if not isinstance(value, str):
            return value

        rendered = value
        for key, replacement in self.available_variables.items():
            rendered = rendered.replace("{{ " + key + " }}", str(replacement))
        rendered = rendered.replace("{{ 42 | strong_password }}", "strong-password-42")
        return rendered


class _NoopTemplar:
    def __init__(self, variables: dict[str, str]) -> None:
        self.available_variables = dict(variables)

    def template(self, value, fail_on_undefined=False):
        return value


class _SplitTemplar(_DummyTemplar):
    def template(self, value, fail_on_undefined=False):
        rendered = super().template(value, fail_on_undefined=fail_on_undefined)
        if not isinstance(rendered, str):
            return rendered

        domain_primary = self.available_variables.get("DOMAIN_PRIMARY")
        if domain_primary:
            rendered = rendered.replace(
                "{{ DOMAIN_PRIMARY.split('.')[0] }}",
                str(domain_primary).split(".")[0],
            )
        return rendered


if __name__ == "__main__":
    unittest.main()
