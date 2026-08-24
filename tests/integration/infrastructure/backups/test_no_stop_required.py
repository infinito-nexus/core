import os
import unittest
from pathlib import Path

import yaml

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES


class TestNoStopRequiredIntegrity(unittest.TestCase):
    def setUp(self):
        self.roles_dir = str(
            Path(str(Path(str(Path(__file__).parent)) / "../../../../roles")).resolve()
        )

    def test_backup_no_stop_required_consistency(self):
        """
        Ensure that if `backup.no_stop_required: true` is set for any services[*]:
          - it's a boolean value
          - the containing service dict has an `image` entry at the same level
        """
        for role in os.listdir(self.roles_dir):
            docker_config_path = str(
                Path(self.roles_dir) / role / ROLE_FILE_META_SERVICES
            )
            if not Path(docker_config_path).is_file():
                continue

            try:
                config = load_yaml_any(docker_config_path) or {}
            except yaml.YAMLError as e:
                self.fail(f"YAML parsing failed for {docker_config_path}: {e}")
                continue

            services = config if isinstance(config, dict) else {}

            for service_key, service in services.items():
                if not isinstance(service, dict):
                    continue
                backup_cfg = service.get("backup", {}) or {}
                if backup_cfg.get("no_stop_required") is True:
                    with self.subTest(role=role, service=service_key):
                        self.assertIsInstance(
                            backup_cfg["no_stop_required"],
                            bool,
                            f"`backup.no_stop_required` in role '{role}', service '{service_key}' must be a boolean.",
                        )
                        self.assertIn(
                            "image",
                            service,
                            f"`image` is required in role '{role}', service '{service_key}' when `backup.no_stop_required` is set to True.",
                        )


if __name__ == "__main__":
    unittest.main()
