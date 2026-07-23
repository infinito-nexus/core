from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.update.docker import _registry_cursor, update_config_versions


class TestRegistryCursor(unittest.TestCase):
    def test_v_prefixed_pin_seeds_cursor(self) -> None:
        self.assertEqual(_registry_cursor("v19.1.1"), "v")

    def test_bare_numeric_pin_scans_from_start(self) -> None:
        self.assertIsNone(_registry_cursor("19.1.1"))


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
