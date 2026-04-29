from __future__ import annotations

import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.service import LookupModule


_SERVICE_REGISTRY = {
    "matomo": {"role": "web-app-matomo"},
    "cdn": {"role": "web-svc-cdn"},
    "css": {"role": "web-svc-cdn", "canonical": "cdn"},
    "logout": {"role": "web-svc-logout"},
    "collab": {"role": "web-svc-collab"},
}


def _run(terms, applications, group_names, service_registry=None):
    patches = [
        patch(
            "plugins.lookup.service.get_merged_applications",
            return_value=applications,
        )
    ]
    if service_registry is not None:
        patches.append(
            patch(
                "plugins.lookup.service.build_service_registry_from_applications",
                return_value=service_registry,
            )
        )
    for p in patches:
        p.start()
    try:
        return LookupModule().run(
            terms,
            variables={"group_names": group_names},
        )
    finally:
        for p in reversed(patches):
            p.stop()


class TestServiceDirect(unittest.TestCase):
    def setUp(self):
        self.applications = {
            "web-app-foo": {
                "services": {
                    "matomo": {"enabled": True, "shared": True},
                    "css": {"enabled": True, "shared": False},
                    "logout": {"enabled": False, "shared": True},
                }
            },
            "web-app-bar": {"services": {}},
        }

    def _get(self, term, group_names=None):
        return _run(
            [term],
            self.applications,
            group_names if group_names is not None else ["web-app-foo"],
            service_registry=_SERVICE_REGISTRY,
        )[0]

    def test_required_true_when_enabled_and_shared(self):
        self.assertTrue(self._get("matomo")["required"])

    def test_required_false_when_enabled_only(self):
        self.assertFalse(self._get("cdn")["required"])

    def test_required_false_when_shared_only(self):
        self.assertFalse(self._get("logout")["required"])

    def test_required_false_when_service_absent(self):
        self.assertFalse(self._get("collab")["required"])

    def test_required_false_when_group_names_do_not_match(self):
        self.assertFalse(self._get("matomo", ["web-app-unknown"])["required"])

    def test_required_true_when_any_app_qualifies(self):
        self.assertTrue(self._get("matomo", ["web-app-bar", "web-app-foo"])["required"])

    def test_enabled_shared_flags_are_aggregated_via_canonical_alias(self):
        result = self._get("cdn")
        self.assertTrue(result["enabled"])
        self.assertFalse(result["shared"])

    def test_lookup_by_role_name_uses_same_primary_service(self):
        by_key = self._get("cdn")
        by_role = self._get("web-svc-cdn")
        self.assertEqual(by_key, by_role)

    def test_multiple_terms(self):
        results = _run(
            ["matomo", "cdn", "logout"],
            self.applications,
            ["web-app-foo"],
            service_registry=_SERVICE_REGISTRY,
        )
        self.assertEqual(len(results), 3)
        self.assertTrue(results[0]["required"])
        self.assertFalse(results[1]["required"])
        self.assertFalse(results[2]["required"])

    def test_empty_terms_returns_empty(self):
        self.assertEqual(
            _run(
                [],
                self.applications,
                ["web-app-foo"],
                service_registry=_SERVICE_REGISTRY,
            ),
            [],
        )


class TestServiceTransitive(unittest.TestCase):
    def setUp(self):
        self.applications = {
            "web-app-nextcloud": {"services": {"collab": {"enabled": True}}},
            "web-svc-collab": {
                "services": {
                    "matomo": {"enabled": True, "shared": True},
                }
            },
        }

    def test_transitive_required_resolved(self):
        result = _run(
            ["matomo"],
            self.applications,
            ["web-app-nextcloud"],
            service_registry=_SERVICE_REGISTRY,
        )[0]
        self.assertTrue(result["required"])

    def test_transitive_requires_shared_at_target(self):
        applications = {
            "web-app-nextcloud": {"services": {"collab": {"enabled": True}}},
            "web-svc-collab": {"services": {"matomo": {"enabled": True}}},
        }
        result = _run(
            ["matomo"],
            applications,
            ["web-app-nextcloud"],
            service_registry=_SERVICE_REGISTRY,
        )[0]
        self.assertFalse(result["required"])

    def test_direct_provider_is_not_required_without_shared_flag(self):
        result = _run(
            ["collab"],
            self.applications,
            ["web-app-nextcloud"],
            service_registry=_SERVICE_REGISTRY,
        )[0]
        self.assertFalse(result["required"])


class TestServiceDiscoveryWithoutExplicitRegistry(unittest.TestCase):
    def test_role_local_provider_metadata_is_discovered_from_applications(self):
        applications = {
            "web-app-dashboard": {
                "services": {
                    "dashboard": {"enabled": False, "shared": True},
                }
            },
            "web-app-foo": {
                "services": {
                    "dashboard": {"enabled": True, "shared": True},
                }
            },
        }

        result = _run(["dashboard"], applications, ["web-app-foo"])[0]
        self.assertEqual(result["role"], "web-app-dashboard")
        self.assertTrue(result["required"])

    def test_provides_and_canonical_are_discovered_from_provider_configs(self):
        applications = {
            "web-app-keycloak": {
                "services": {
                    "keycloak": {
                        "enabled": False,
                        "shared": True,
                        "provides": "oidc",
                    }
                }
            },
            "web-svc-cdn": {
                "services": {
                    "cdn": {"enabled": False, "shared": True},
                    "css": {"enabled": False, "shared": True, "canonical": "cdn"},
                }
            },
            "web-app-foo": {
                "services": {
                    "oidc": {"enabled": True, "shared": True},
                    "css": {"enabled": True, "shared": False},
                }
            },
        }

        oidc = _run(["oidc"], applications, ["web-app-foo"])[0]
        cdn = _run(["cdn"], applications, ["web-app-foo"])[0]

        self.assertEqual(oidc["role"], "web-app-keycloak")
        self.assertTrue(oidc["required"])
        self.assertEqual(cdn["role"], "web-svc-cdn")
        self.assertTrue(cdn["enabled"])
        self.assertFalse(cdn["required"])


class TestServiceCycleGuard(unittest.TestCase):
    def test_cycle_does_not_loop(self):
        applications = {
            "svc-a": {"services": {"svc-b": {"enabled": True}}},
            "svc-b": {"services": {"svc-a": {"enabled": True}}},
        }
        service_registry = {
            "svc-a": {"role": "svc-a"},
            "svc-b": {"role": "svc-b"},
            "logout": {"role": "web-svc-logout"},
        }
        result = _run(
            ["logout"],
            applications,
            ["svc-a"],
            service_registry=service_registry,
        )[0]
        self.assertFalse(result["required"])

    def test_cycle_found_if_service_present(self):
        applications = {
            "svc-a": {
                "services": {
                    "svc-b": {"enabled": True},
                    "logout": {"enabled": True, "shared": True},
                }
            },
            "svc-b": {"services": {"svc-a": {"enabled": True}}},
        }
        service_registry = {
            "svc-a": {"role": "svc-a"},
            "svc-b": {"role": "svc-b"},
            "logout": {"role": "web-svc-logout"},
        }
        result = _run(
            ["logout"],
            applications,
            ["svc-b"],
            service_registry=service_registry,
        )[0]
        self.assertTrue(result["required"])


class TestServiceErrors(unittest.TestCase):
    def test_raises_when_group_names_not_list(self):
        with patch("plugins.lookup.service.get_merged_applications", return_value={}):
            with self.assertRaises(AnsibleError):
                LookupModule().run(
                    ["matomo"],
                    variables={"group_names": "not-a-list"},
                )

    def test_raises_when_term_empty(self):
        with self.assertRaises(AnsibleError):
            _run(["   "], {}, [], service_registry=_SERVICE_REGISTRY)

    def test_raises_when_term_unknown(self):
        with self.assertRaises(AnsibleError):
            _run(["totally-unknown-key"], {}, [], service_registry=_SERVICE_REGISTRY)


if __name__ == "__main__":
    unittest.main()
