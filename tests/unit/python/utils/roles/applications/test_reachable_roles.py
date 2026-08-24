"""Unit tests for the whitelist-scoped dependency closure."""

from __future__ import annotations

import unittest

from utils.roles.applications import in_group_deps as deps_mod

SERVICE_REGISTRY = {
    "mariadb": {"role": "svc-db-mariadb"},
    "ldap": {"role": "svc-db-openldap"},
    "postgres": {"role": "svc-db-postgres"},
}


def _uses(service_key):
    return {"services": {service_key: {"enabled": True, "shared": True}}}


APPS = {
    "web-app-alpha": _uses("mariadb"),
    "web-app-beta": _uses("postgres"),
    "web-app-solo": {},
    "svc-db-mariadb": _uses("ldap"),
    "svc-db-openldap": {},
    "svc-db-postgres": {},
}


def _resolver(mapping):
    return lambda role, roles_dir: (mapping or {}).get(role, [])


class TestReachableRoles(unittest.TestCase):
    def _closure(self, seeds, meta_deps=None):
        return deps_mod.reachable_roles(
            APPS,
            seeds,
            project_root="/unused",
            roles_dir="/unused",
            service_registry=SERVICE_REGISTRY,
            meta_deps_resolver=_resolver(meta_deps),
        )

    def test_no_seed_reaches_nothing(self):
        self.assertEqual(self._closure([]), set())

    def test_an_app_without_dependencies_reaches_only_itself(self):
        self.assertEqual(self._closure(["web-app-solo"]), {"web-app-solo"})

    def test_service_edges_are_followed_transitively(self):
        self.assertEqual(
            self._closure(["web-app-alpha"]),
            {"web-app-alpha", "svc-db-mariadb", "svc-db-openldap"},
        )

    def test_an_unrelated_app_stays_outside_the_closure(self):
        self.assertNotIn("web-app-beta", self._closure(["web-app-alpha"]))
        self.assertNotIn("svc-db-postgres", self._closure(["web-app-alpha"]))

    def test_meta_dependencies_are_followed(self):
        closure = self._closure(
            ["web-app-solo"], meta_deps={"web-app-solo": ["svc-db-postgres"]}
        )
        self.assertEqual(closure, {"web-app-solo", "svc-db-postgres"})

    def test_seeding_every_app_reaches_every_app(self):
        self.assertEqual(self._closure(sorted(APPS)), set(APPS))


if __name__ == "__main__":
    unittest.main()
