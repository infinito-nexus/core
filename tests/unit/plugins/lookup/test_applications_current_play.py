from __future__ import annotations

import unittest
from unittest.mock import patch

from plugins.lookup.applications_current_play import (
    LookupModule,
    _reset_cache_for_tests,
)


# Per req-008 the materialised payload moved from
# `applications.<app>.compose.services.<X>` to `applications.<app>.services.<X>`.
SAMPLE_APPS = {
    "web-svc-html": {},
    "web-svc-legal": {},
    "web-svc-file": {"services": {"file": {"enabled": False, "shared": True}}},
    "web-svc-asset": {
        "services": {
            "asset": {"enabled": False, "shared": True},
            "file": {"enabled": True, "shared": True},
        }
    },
    "web-app-dashboard": {
        "services": {"dashboard": {"enabled": False, "shared": True}}
    },
    "web-app-matomo": {"services": {"matomo": {"enabled": False, "shared": True}}},
    "svc-db-openldap": {
        "services": {"openldap": {"enabled": False, "shared": True, "provides": "ldap"}}
    },
    "svc-db-mariadb": {"services": {"mariadb": {"enabled": False, "shared": True}}},
}


def _run(group_names, applications=None, meta_deps_map=None, service_registry=None):
    lm = LookupModule()
    lm._meta_deps = lambda role, roles_dir: (meta_deps_map or {}).get(role, [])
    apps = applications if applications is not None else SAMPLE_APPS
    patches = [
        patch(
            "plugins.lookup.applications_current_play.get_merged_applications",
            return_value=apps,
        )
    ]
    if service_registry is not None:
        patches.append(
            patch(
                "plugins.lookup.applications_current_play.build_service_registry_from_applications",
                return_value=service_registry,
            )
        )
    for p in patches:
        p.start()
    try:
        return lm.run(
            [],
            variables={"group_names": group_names},
        )[0]
    finally:
        for p in reversed(patches):
            p.stop()


class TestApplicationsIfGroupAndAllDeps(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def tearDown(self) -> None:
        _reset_cache_for_tests()

    def test_direct_group_only(self):
        result = _run(["web-svc-html"])
        self.assertIn("web-svc-html", result)
        self.assertNotIn("web-svc-legal", result)

    def test_unknown_group_returns_empty(self):
        self.assertEqual(_run(["nonexistent"]), {})

    def test_empty_group_names_returns_empty(self):
        self.assertEqual(_run([]), {})

    def test_meta_dep_included(self):
        result = _run(
            ["web-svc-legal"],
            meta_deps_map={"web-svc-legal": ["web-svc-html"]},
        )
        self.assertIn("web-svc-legal", result)
        self.assertIn("web-svc-html", result)

    def test_meta_dep_not_in_applications_ignored(self):
        result = _run(
            ["web-svc-legal"],
            meta_deps_map={"web-svc-legal": ["some-unknown-role"]},
        )
        self.assertIn("web-svc-legal", result)
        self.assertNotIn("some-unknown-role", result)

    def test_recursive_meta_deps(self):
        result = _run(
            ["web-svc-legal"],
            meta_deps_map={
                "web-svc-legal": ["web-svc-asset"],
                "web-svc-asset": ["web-svc-file"],
            },
        )
        self.assertIn("web-svc-legal", result)
        self.assertIn("web-svc-asset", result)
        self.assertIn("web-svc-file", result)

    def test_cycle_in_meta_deps_does_not_hang(self):
        result = _run(
            ["web-svc-html"],
            meta_deps_map={
                "web-svc-html": ["web-svc-legal"],
                "web-svc-legal": ["web-svc-html"],
            },
        )
        self.assertIn("web-svc-html", result)
        self.assertIn("web-svc-legal", result)

    def test_service_dep_enabled_and_shared(self):
        apps = dict(SAMPLE_APPS)
        apps["web-svc-legal"] = {
            "services": {"matomo": {"enabled": True, "shared": True}}
        }
        result = _run(["web-svc-legal"], applications=apps)
        self.assertIn("web-svc-legal", result)
        self.assertIn("web-app-matomo", result)

    def test_service_dep_not_included_when_enabled_false(self):
        apps = dict(SAMPLE_APPS)
        apps["web-svc-legal"] = {
            "services": {"matomo": {"enabled": False, "shared": True}}
        }
        self.assertNotIn("web-app-matomo", _run(["web-svc-legal"], applications=apps))

    def test_service_dep_not_included_when_shared_false(self):
        apps = dict(SAMPLE_APPS)
        apps["web-svc-legal"] = {
            "services": {"matomo": {"enabled": True, "shared": False}}
        }
        self.assertNotIn("web-app-matomo", _run(["web-svc-legal"], applications=apps))

    def test_service_not_in_registry_is_ignored(self):
        apps = dict(SAMPLE_APPS)
        apps["web-svc-legal"] = {
            "services": {"unknown-svc": {"enabled": True, "shared": True}}
        }
        result = _run(["web-svc-legal"], applications=apps)
        self.assertIn("web-svc-legal", result)

    def test_service_dep_with_provides_is_resolved(self):
        apps = dict(SAMPLE_APPS)
        apps["web-svc-legal"] = {
            "services": {"ldap": {"enabled": True, "shared": True}}
        }
        result = _run(["web-svc-legal"], applications=apps)
        self.assertIn("svc-db-openldap", result)

    def test_service_dep_for_database_role_uses_direct_service_name(self):
        apps = dict(SAMPLE_APPS)
        apps["web-svc-legal"] = {
            "services": {"mariadb": {"enabled": True, "shared": True}}
        }
        result = _run(["web-svc-legal"], applications=apps)
        self.assertIn("svc-db-mariadb", result)

    def test_mixed_meta_and_service_deps(self):
        apps = dict(SAMPLE_APPS)
        apps["web-svc-legal"] = {
            "services": {"matomo": {"enabled": True, "shared": True}}
        }
        result = _run(
            ["web-svc-legal"],
            applications=apps,
            meta_deps_map={"web-svc-legal": ["web-svc-html"]},
        )
        self.assertIn("web-svc-legal", result)
        self.assertIn("web-svc-html", result)
        self.assertIn("web-app-matomo", result)

    def test_transitive_service_dep(self):
        apps = dict(SAMPLE_APPS)
        apps["web-svc-asset"] = {
            "services": {"ldap": {"enabled": True, "shared": True}}
        }
        result = _run(
            ["web-svc-legal"],
            applications=apps,
            meta_deps_map={"web-svc-legal": ["web-svc-asset"]},
        )
        self.assertIn("web-svc-legal", result)
        self.assertIn("web-svc-asset", result)
        self.assertIn("svc-db-openldap", result)

    def test_returns_full_config_not_just_ids(self):
        apps = {
            "web-svc-legal": {"some_key": "some_value"},
            "web-svc-html": {"other_key": 42},
        }
        result = _run(
            ["web-svc-legal"],
            applications=apps,
            meta_deps_map={"web-svc-legal": ["web-svc-html"]},
            service_registry={},
        )
        self.assertEqual(result["web-svc-legal"]["some_key"], "some_value")
        self.assertEqual(result["web-svc-html"]["other_key"], 42)

    def test_missing_applications_falls_back_to_lookup(self):
        lm = LookupModule()
        lm._meta_deps = lambda r, d: []
        self.assertEqual(lm.run([], variables={"group_names": []})[0], {})

    def test_invalid_group_names_raises(self):
        lm = LookupModule()
        lm._meta_deps = lambda r, d: []
        with self.assertRaises(Exception):
            lm.run(
                [], variables={"applications": SAMPLE_APPS, "group_names": "not-a-list"}
            )


if __name__ == "__main__":
    unittest.main()
