import os
import unittest
from pathlib import Path

import yaml

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES


class TestStopRequiredIntegrity(unittest.TestCase):
    def setUp(self):
        self.roles_dir = str(
            Path(str(Path(str(Path(__file__).parent)) / "../../../../roles")).resolve()
        )

    def test_backup_stop_required_consistency(self):
        """
        Ensure that every services[*] declaring `backup.stop_required`:
          - sets it to a boolean value
          - carries an `image` or `custom` entry at the same level when it is
            false, so the image can be handed to baudolo
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
                if "stop_required" not in backup_cfg:
                    continue
                with self.subTest(role=role, service=service_key):
                    self.assertIsInstance(
                        backup_cfg["stop_required"],
                        bool,
                        f"`backup.stop_required` in role '{role}', service '{service_key}' must be a boolean.",
                    )
                    if backup_cfg["stop_required"] is False:
                        self.assertTrue(
                            service.get("image") or service.get("custom"),
                            f"`image` or `custom` is required in role '{role}', service '{service_key}' when `backup.stop_required` is set to False.",
                        )


if __name__ == "__main__":
    unittest.main()
