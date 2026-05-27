import unittest
from collections import defaultdict

from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)

from . import PROJECT_ROOT


class TestServicesCanonical(unittest.TestCase):
    """Discovered canonical aliases from role-local configs must be internally consistent."""

    def setUp(self):
        self.repo_root = PROJECT_ROOT
        self.service_registry = build_service_registry_from_roles_dir(
            self.repo_root / "roles"
        )
        self.assertGreater(
            len(self.service_registry),
            0,
            "discovered service registry must not be empty",
        )

        self.role_to_keys = defaultdict(list)
        for key, entry in self.service_registry.items():
            role = entry.get("role")
            if role:
                self.role_to_keys[role].append(key)

    def test_shared_roles_have_exactly_one_primary_key(self):
        for role, keys in self.role_to_keys.items():
            if len(keys) < 2:
                continue
            primaries = [k for k in keys if "canonical" not in self.service_registry[k]]
            with self.subTest(role=role):
                self.assertEqual(len(primaries), 1)

    def test_canonical_target_exists(self):
        for key, entry in self.service_registry.items():
            canonical = entry.get("canonical")
            if canonical is None:
                continue
            with self.subTest(key=key):
                self.assertIn(canonical, self.service_registry)

    def test_canonical_target_has_same_role(self):
        for key, entry in self.service_registry.items():
            canonical = entry.get("canonical")
            if canonical is None:
                continue
            with self.subTest(key=key):
                self.assertEqual(
                    entry.get("role"),
                    self.service_registry[canonical].get("role"),
                )

    def test_canonical_target_is_not_itself_an_alias(self):
        for key, entry in self.service_registry.items():
            canonical = entry.get("canonical")
            if canonical is None:
                continue
            with self.subTest(key=key):
                self.assertNotIn("canonical", self.service_registry[canonical])

    def test_unique_roles_do_not_declare_canonical(self):
        for key, entry in self.service_registry.items():
            canonical = entry.get("canonical")
            if canonical is None:
                continue
            role = entry.get("role")
            with self.subTest(key=key):
                self.assertGreater(len(self.role_to_keys.get(role, [])), 1)


if __name__ == "__main__":
    unittest.main()
