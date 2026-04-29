import unittest
import os
import yaml


class TestBackupsEnabledIntegrity(unittest.TestCase):
    def setUp(self):
        # Path to the roles directory
        self.roles_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../../roles")
        )

    def test_backups_enabled_image_consistency(self):
        """
        Ensure that if `backups.enabled` is set for any services[*]:
          - it's a boolean value
          - the containing service dict has an `image` entry at the same level
        """
        for role in os.listdir(self.roles_dir):
            docker_config_path = os.path.join(
                self.roles_dir, role, "meta", "services.yml"
            )
            if not os.path.isfile(docker_config_path):
                continue

            with open(docker_config_path, "r") as f:
                try:
                    config = yaml.safe_load(f) or {}
                except yaml.YAMLError as e:
                    self.fail(f"YAML parsing failed for {docker_config_path}: {e}")
                    continue

            # Per req-008 the file root of meta/services.yml IS the
            # services map (no `compose.services` wrapper).
            services = config if isinstance(config, dict) else {}

            for service_key, service in services.items():
                if not isinstance(service, dict):
                    continue

                backups_cfg = service.get("backups", {}) or {}
                if "enabled" in backups_cfg:
                    with self.subTest(role=role, service=service_key):
                        self.assertIsInstance(
                            backups_cfg["enabled"],
                            bool,
                            f"`backups.enabled` in role '{role}', service '{service_key}' must be a boolean.",
                        )
                        self.assertIn(
                            "image",
                            service,
                            f"`image` is required in role '{role}', service '{service_key}' when `backups.enabled` is defined.",
                        )


if __name__ == "__main__":
    unittest.main()
