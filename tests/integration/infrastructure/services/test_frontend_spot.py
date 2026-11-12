import unittest

from utils.cache.files import read_text
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    load_applications_from_roles_dir,
    ordered_primary_service_entries,
)

from . import PROJECT_ROOT


class TestFrontendServiceSpot(unittest.TestCase):
    def setUp(self):
        self.repo_root = PROJECT_ROOT
        self.roles_dir = self.repo_root / "roles"
        self.applications = load_applications_from_roles_dir(self.roles_dir)
        self.service_registry = build_service_registry_from_roles_dir(self.roles_dir)
        self.ordered = ordered_primary_service_entries(
            self.service_registry,
            self.roles_dir,
        )

    def _index(self, role_name: str) -> int:
        for index, entry in enumerate(self.ordered):
            if entry["role"] == role_name:
                return index
        self.fail(f"Role {role_name} not found in ordered service registry")
        return -1

    def test_bucket_order_is_monotonic(self):
        bucket_order = {
            "universal": 0,
            "workstation": 1,
            "server": 2,
            "web-svc": 3,
            "web-app": 4,
        }
        actual = [bucket_order[entry["bucket"]] for entry in self.ordered]
        self.assertEqual(actual, sorted(actual))

    def test_dashboard_is_loaded_after_matomo(self):
        self.assertLess(self._index("web-app-matomo"), self._index("web-app-dashboard"))

    def test_discourse_is_loaded_after_matomo(self):
        self.assertLess(self._index("web-app-matomo"), self._index("web-app-discourse"))

    def test_keycloak_respects_run_after_dependencies(self):
        self.assertLess(self._index("web-app-matomo"), self._index("web-app-keycloak"))
        self.assertLess(
            self._index("web-app-stalwart"), self._index("web-app-keycloak")
        )
        self.assertLess(self._index("web-app-email"), self._index("web-app-keycloak"))

    def test_front_proxy_falls_back_to_canonical_port_and_domain(self):
        tasks = self.roles_dir / "svc-stack" / "tasks"
        vhost = read_text(str(tasks / "proxy" / "domain.yml"))
        self.assertIn("lookup('config', front_proxy_application_id,", vhost)
        self.assertIn(".ports.local.http", vhost)
        self.assertIn(
            "lookup('domain', application_id)", read_text(str(tasks / "proxy.yml"))
        )


if __name__ == "__main__":
    unittest.main()
