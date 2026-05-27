import os
import unittest
from pathlib import Path

import yaml

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES


class TestNoStopRequiredIntegrity(unittest.TestCase):
    def setUp(self):
        # Path to the roles directory
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
                # Ensure config is at least an empty dict if YAML is empty or null
                config = load_yaml_any(docker_config_path) or {}
            except yaml.YAMLError as e:
                self.fail(f"YAML parsing failed for {docker_config_path}: {e}")
                continue

            # Per the file root of meta/services.yml IS the
            # services map (no `compose.services` wrapper).
            services = config if isinstance(config, dict) else {}

            for service_key, service in services.items():
                if not isinstance(service, dict):
                    continue
                backup_cfg = service.get("backup", {}) or {}
                # Check if no_stop_required is explicitly True
                if backup_cfg.get("no_stop_required") is True:
                    with self.subTest(role=role, service=service_key):
                        # Must be a boolean
                        self.assertIsInstance(
                            backup_cfg["no_stop_required"],
                            bool,
                            f"`backup.no_stop_required` in role '{role}', service '{service_key}' must be a boolean.",
                        )
                        # Must have `image` defined at the service level
                        self.assertIn(
                            "image",
                            service,
                            f"`image` is required in role '{role}', service '{service_key}' when `backup.no_stop_required` is set to True.",
                        )


if __name__ == "__main__":
    unittest.main()
