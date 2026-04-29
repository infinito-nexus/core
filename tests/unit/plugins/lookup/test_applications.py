from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.errors import AnsibleError

from plugins.lookup.applications import LookupModule, _reset_cache_for_tests


def _write_config(base_dir: Path, application_id: str, config: dict) -> None:
    config_path = base_dir / "roles" / application_id / "meta" / "services.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")


class TestApplicationsLookup(unittest.TestCase):
    def setUp(self) -> None:
        self.lookup = LookupModule()
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmpdir.name)
        os.chdir(self._tmp)
        _reset_cache_for_tests()

        _write_config(
            self._tmp,
            "web-app-foo",
            {"smtp": {"host": "mail.example.org"}, "feature": {"enabled": True}},
        )
        _write_config(self._tmp, "web-app-bar", {})

    def tearDown(self) -> None:
        _reset_cache_for_tests()
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_returns_full_mapping(self) -> None:
        # Per req-008 the file root of meta/services.yml is the services map,
        # so the loader puts it under `services` in the materialised payload.
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


if __name__ == "__main__":
    unittest.main()
