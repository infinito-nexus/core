from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.docker import (
    _registry_cursor,
    collect_entries,
    sourced_services,
    update_config_versions,
)

SOURCED = """bundled:
  image: example/app
  version: v1.0.0
  update:
    type: http_regex
    url: https://example.invalid/bundle
    pattern: "app:(v[0-9.]+)"
tracked:
  image: example/side
  version: v2.0.0
  other_version: v3.0.0
  update:
    - key: other_version
      type: git_tags
      repository: https://example.invalid/side.git
plain:
  image: example/plain
  version: v4.0.0
"""


class TestRegistryCursor(unittest.TestCase):
    def test_v_prefixed_pin_seeds_cursor(self) -> None:
        self.assertEqual(_registry_cursor("v19.1.1"), "v")

    def test_bare_numeric_pin_scans_from_start(self) -> None:
        self.assertIsNone(_registry_cursor("19.1.1"))


class TestDeclaredSource(unittest.TestCase):
    def test_a_version_with_its_own_source_is_left_to_that_source(self) -> None:
        root = Path(tempfile.mkdtemp())
        config = root / "roles" / "web-app-example" / ROLE_FILE_META_SERVICES
        config.parent.mkdir(parents=True)
        config.write_text(SOURCED, encoding="utf-8")

        self.assertEqual(sourced_services(config), {"bundled"})
        self.assertEqual(
            sorted(entry.service for entry in collect_entries(root)),
            ["plain", "tracked"],
        )


class TestUpdateDocker(unittest.TestCase):
    def test_update_config_versions_updates_only_target_services(self) -> None:
        original = """moodle:
  version:            "4.5" # Keep comment
  image:              bitnamilegacy/moodle
nginx:
  version:            alpine
  image:              nginx
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "main.yml"
            config_path.write_text(original, encoding="utf-8")

            changed = update_config_versions(config_path, {"moodle": "5.0"})

            self.assertTrue(changed)
            updated = read_text(str(config_path))
            self.assertIn('version:            "5.0" # Keep comment', updated)
            self.assertIn("version:            alpine", updated)
            self.assertNotIn('version:            "4.5" # Keep comment', updated)


if __name__ == "__main__":
    unittest.main()
