import unittest
from pathlib import Path

import yaml

from plugins.lookup.service import LookupModule


class TestServiceTransitiveDependencies(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[3]
        self.applications = {
            "web-app-dashboard": self._load_yaml(
                "roles", "web-app-dashboard", "meta", "services.yml"
            ),
            "web-svc-asset": self._load_yaml(
                "roles", "web-svc-asset", "meta", "services.yml"
            ),
            "web-svc-file": self._load_yaml(
                "roles", "web-svc-file", "meta", "services.yml"
            ),
        }

    def _load_yaml(self, *parts):
        path = self.repo_root.joinpath(*parts)
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def test_dashboard_needs_file_transitively_via_asset_service(self):
        result = LookupModule().run(
            ["file"],
            variables={
                "applications": self.applications,
                "group_names": ["web-app-dashboard"],
            },
        )[0]

        self.assertTrue(result["required"])
        self.assertEqual(result["id"], "file")
        self.assertEqual(result["role"], "web-svc-file")


if __name__ == "__main__":
    unittest.main()
