import unittest
from pathlib import Path

try:
    from plugins.filter.docker.service_enabled import FilterModule
except ModuleNotFoundError:
    import sys

    sys.path.insert(
        0,
        str(
            Path(
                str(Path(str(Path(__file__).parent)) / "../../../../plugins/filter")
            ).resolve()
        ),
    )
    from docker.service_enabled import FilterModule


class TestIsDockerServiceEnabledFilter(unittest.TestCase):
    def setUp(self):
        self.filter = FilterModule().filters()["is_docker_service_enabled"]

    def test_enabled_true(self):
        applications = {
            "app1": {
                "services": {
                    "redis": {"enabled": True},
                    "database": {"enabled": True},
                }
            }
        }
        self.assertTrue(self.filter(applications, "app1", "redis"))
        self.assertTrue(self.filter(applications, "app1", "database"))

    def test_enabled_false(self):
        applications = {
            "app1": {
                "services": {
                    "redis": {"enabled": False},
                    "database": {"enabled": False},
                }
            }
        }
        self.assertFalse(self.filter(applications, "app1", "redis"))
        self.assertFalse(self.filter(applications, "app1", "database"))

    def test_missing_enabled_key(self):
        applications = {
            "app1": {
                "services": {
                    "redis": {},
                    "database": {},
                }
            }
        }
        self.assertFalse(self.filter(applications, "app1", "redis"))
        self.assertFalse(self.filter(applications, "app1", "database"))

    def test_missing_service_key(self):
        applications = {"app1": {"services": {}}}
        self.assertFalse(self.filter(applications, "app1", "redis"))
        self.assertFalse(self.filter(applications, "app1", "database"))

    def test_missing_services_key(self):
        applications = {"app1": {}}
        self.assertFalse(self.filter(applications, "app1", "redis"))

    def test_missing_app_id(self):
        applications = {"other_app": {}}
        self.assertFalse(self.filter(applications, "app1", "redis"))

    def test_applications_is_none(self):
        applications = None
        self.assertFalse(self.filter(applications, "app1", "database"))


if __name__ == "__main__":
    unittest.main()
