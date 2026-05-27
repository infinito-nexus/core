from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.update.docker import update_config_versions


class TestUpdateDocker(unittest.TestCase):
    def test_update_config_versions_updates_only_target_services(self) -> None:
        # The file root of meta/services.yml IS the services map (no
        # `compose.services` envelope), so service keys are at indent 0.
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
