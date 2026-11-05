import importlib.util
import sys
import unittest
from unittest.mock import patch

from utils.domains.default_primary import default_domain_primary

from . import PROJECT_ROOT

DOMAIN = default_domain_primary()


# Dynamically load the module under test from the Ansible role's files directory
def load_optimizer_module():
    module_path = str(
        PROJECT_ROOT / "roles" / "svc-opt-ssd-hdd" / "files" / "python" / "script.py"
    )
    spec = importlib.util.spec_from_file_location("storage_optimizer", module_path)
    optimizer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = optimizer
    spec.loader.exec_module(optimizer)
    return optimizer


storage_optimizer = load_optimizer_module()


class TestHealthCheckLogic(unittest.TestCase):
    def setUp(self):
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


class TestIsDatabase(unittest.TestCase):
    def test_classification(self):
        test_cases = [
            ("postgres_custom:18", True),
            ("openldap_custom:13.7-slim", True),
            ("mariadb_custom:11.8", True),
            ("postgis/postgis:17-3.5", True),
            ("valkey/valkey:8", True),
            ("docker.io/library/postgres:18", True),
            ("ghcr.io/infinito-nexus/mirror/docker.io/library/postgres:18", True),
            (f"registry.{DOMAIN}:5000/openldap_custom:13.7-slim", True),
            ("postgres@sha256:" + "0" * 64, True),
            ("docker.elastic.co/elasticsearch/elasticsearch:9.1.0", True),
            ("bigbluebutton_custom:v3.0.39", False),
            (f"registry.{DOMAIN}:5000/nextcloud:31", False),
            ("ghcr.io/ldapaccountmanager/lam:9", False),
            ("phpldapadmin/phpldapadmin:2", False),
        ]
        for image_name, expected in test_cases:
            self.assertEqual(
                storage_optimizer.is_database(image_name),
                expected,
                f"Image {image_name} expected {expected}",
            )


if __name__ == "__main__":
    unittest.main()
