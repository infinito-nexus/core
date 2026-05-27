import importlib.util
import sys
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT


# Dynamically load the module under test from the Ansible role's files directory
def load_optimizer_module():
    module_path = str(
        PROJECT_ROOT / "roles" / "svc-opt-ssd-hdd" / "files" / "script.py"
    )
    spec = importlib.util.spec_from_file_location("storage_optimizer", module_path)
    optimizer = importlib.util.module_from_spec(spec)
    # Register module so patch('storage_optimizer...') works
    sys.modules[spec.name] = optimizer
    spec.loader.exec_module(optimizer)
    return optimizer


storage_optimizer = load_optimizer_module()


class TestHealthCheckLogic(unittest.TestCase):
    def setUp(self):
        # Prevent sleeping delays in inline loops
        patcher = patch("storage_optimizer.time.sleep", return_value=None)
        self.sleep_patcher = patcher.start()
        self.addCleanup(self.sleep_patcher.stop)

    @patch("storage_optimizer.run_command")
    def test_has_healthcheck_true(self, mock_run):
        mock_run.return_value = '{"Status":"starting","FailingStreak":0}'
        self.assertTrue(storage_optimizer.has_healthcheck("container-id"))

    @patch("storage_optimizer.run_command")
    def test_has_healthcheck_false(self, mock_run):
        mock_run.return_value = "null"
        self.assertFalse(storage_optimizer.has_healthcheck("container-id"))

    @patch("storage_optimizer.get_image")
    def test_has_container_with_database(self, mock_get_image):
        test_cases = [
            ("postgres:13", True),
            ("mariadb:latest", True),
            ("redis:6", True),
            ("mongo:4", True),
            ("nginx:alpine", False),
        ]
        for image_name, expected in test_cases:
            mock_get_image.return_value = image_name
            result = storage_optimizer.has_container_with_database(["any"])
            self.assertEqual(
                result, expected, f"Image {image_name} expected {expected}"
            )


if __name__ == "__main__":
    unittest.main()
