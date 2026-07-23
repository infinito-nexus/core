import unittest

from plugins.lookup.service import LookupModule
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    load_applications_from_roles_dir,
)

from . import PROJECT_ROOT


class TestServicesResolvable(unittest.TestCase):
    """Discovered service keys and provider roles must resolve via the service lookup."""

    @classmethod
    def setUpClass(cls):
        cls.repo_root = PROJECT_ROOT
        cls.roles_dir = cls.repo_root / "roles"
        cls.applications = load_applications_from_roles_dir(cls.roles_dir)
        cls.service_registry = build_service_registry_from_roles_dir(cls.roles_dir)

    def setUp(self):
        self.assertGreater(
            len(self.service_registry),
            0,
            "discovered service registry must not be empty",
        )

    def _run(self, term):
        return LookupModule().run(
            [term],
            variables={
                "applications": self.applications,
                "group_names": [],
            },
            service_registry=self.service_registry,
        )[0]

    def test_all_keys_resolvable(self):
        for key in self.service_registry:
            with self.subTest(key=key):
                result = self._run(key)
                self.assertEqual(result["id"], key)

    def test_all_primary_roles_resolve_to_primary_key(self):
        seen_roles = set()
        for key, entry in self.service_registry.items():
            if "canonical" in entry:
                continue
            role = entry.get("role")
            if not role or role in seen_roles:
                continue
            seen_roles.add(role)
            with self.subTest(role=role, expected_key=key):
                result = self._run(role)
                self.assertEqual(result["role"], role)
                self.assertEqual(result["id"], key)

    def test_key_and_role_produce_identical_result_for_primary_keys(self):
        for key, entry in self.service_registry.items():
            if "canonical" in entry:
                continue
            role = entry.get("role")
            if not role:
                continue
            with self.subTest(key=key):
                self.assertEqual(self._run(key), self._run(role))


if __name__ == "__main__":
    unittest.main()
