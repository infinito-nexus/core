from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleError

from plugins.lookup.applications import LookupModule, _reset_cache_for_tests
from utils.cache import base as cache_base
from utils.cache.carrier import merged_applications_cache_key
from utils.cache.yaml import dump_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES


def _write_config(base_dir: Path, application_id: str, config: dict) -> None:
    config_path = base_dir / "roles" / application_id / ROLE_FILE_META_SERVICES
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(dump_yaml_str(config), encoding="utf-8")


class TestApplicationsLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _reset_cache_for_tests()
        cls.addClassCleanup(_reset_cache_for_tests)

    def setUp(self) -> None:
        cache_base._reset()
        self.lookup = LookupModule()
        self._cwd = str(Path.cwd())
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmpdir.name)
        os.chdir(self._tmp)

        _write_config(
            self._tmp,
            "web-app-foo",
            {"smtp": {"host": "mail.example.org"}, "feature": {"enabled": True}},
        )
        _write_config(self._tmp, "web-app-bar", {})

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_returns_full_mapping(self) -> None:
        result = self.lookup.run([], variables={}, roles_dir=str(self._tmp / "roles"))[
            0
        ]
        self.assertIn("web-app-foo", result)
        self.assertIn("web-app-bar", result)
        self.assertEqual(
            result["web-app-foo"]["services"]["smtp"]["host"], "mail.example.org"
        )

    def test_returns_single_entry(self) -> None:
        result = self.lookup.run(
            ["web-app-foo"],
            variables={},
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result["services"]["smtp"]["host"], "mail.example.org")

    def test_applies_inventory_override(self) -> None:
        result = self.lookup.run(
            ["web-app-foo"],
            variables={
                "applications": {
                    "web-app-foo": {
                        "services": {"smtp": {"host": "override.example.org"}}
                    }
                }
            },
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result["services"]["smtp"]["host"], "override.example.org")
        self.assertTrue(result["services"]["feature"]["enabled"])

    def test_ignores_non_mapping_runtime_applications_placeholder(self) -> None:
        result = self.lookup.run(
            ["web-app-foo"],
            variables={"applications": "web-app-foo"},
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result["services"]["smtp"]["host"], "mail.example.org")
        self.assertTrue(result["services"]["feature"]["enabled"])

    def test_missing_entry_raises_without_default(self) -> None:
        with self.assertRaises(AnsibleError):
            self.lookup.run(
                ["web-app-missing"],
                variables={},
                roles_dir=str(self._tmp / "roles"),
            )

    def test_missing_entry_returns_default_when_provided(self) -> None:
        default_value = {"fallback": True}
        result = self.lookup.run(
            ["web-app-missing", default_value],
            variables={},
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result, default_value)

    def test_carrier_form_returns_cache_key_and_full_mapping(self) -> None:
        variables = {
            "applications": {
                "web-app-foo": {"services": {"smtp": {"host": "override.example.org"}}}
            }
        }
        roles_dir = str(self._tmp / "roles")
        result = self.lookup.run(
            [], variables=variables, roles_dir=roles_dir, carrier=True
        )[0]
        key = merged_applications_cache_key(variables, roles_dir=roles_dir)
        self.assertEqual(result["key"], [key[0], list(key[1])])
        self.assertEqual(
            result["applications"]["web-app-foo"]["services"]["smtp"]["host"],
            "override.example.org",
        )

    def test_carrier_form_rejects_terms(self) -> None:
        with self.assertRaises(AnsibleError):
            self.lookup.run(
                ["web-app-foo"],
                variables={},
                roles_dir=str(self._tmp / "roles"),
                carrier=True,
            )


if __name__ == "__main__":
    unittest.main()
