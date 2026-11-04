"""Unit tests for ``kc_app_ldap_scopes`` in ``build_realm_rbac_groups.py``."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

PLUGIN = (
    Path(__file__).parent
    / "../../../../../../roles/web-app-keycloak/filter_plugins/build_realm_rbac_groups.py"
).resolve()


def _load():
    spec = importlib.util.spec_from_file_location("build_realm_rbac_groups", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.kc_app_ldap_scopes


APP = "web-app-wordpress"


class TestAppLdapScopes(unittest.TestCase):
    def setUp(self):
        self.scopes = _load()

    def test_tenant_unaware_app_keeps_the_prefix_filter(self):
        apps = {APP: {"rbac": {"roles": {"editor": {}}}}}
        self.assertEqual(
            self.scopes(apps, APP),
            {"filter": f"(&(objectClass=groupOfNames)(cn={APP}-*))", "tenants": []},
        )

    def test_tenant_aware_app_splits_global_roles_from_tenants(self):
        apps = {
            APP: {
                "rbac": {
                    "tenancy": {"axis": "domain"},
                    "roles": {
                        "editor": {},
                        "network-administrator": {"scope": "global"},
                    },
                },
                "domains": {"canonical": ["Blog.Example.org", "shop.example.org/"]},
            }
        }
        result = self.scopes(apps, APP)
        self.assertEqual(
            result["filter"],
            f"(&(objectClass=groupOfNames)(|(cn={APP}-network-administrator)"
            f"(cn={APP}-blog.example.org)(cn={APP}-shop.example.org)))",
        )
        self.assertEqual(
            result["tenants"],
            [
                {
                    "tenant": "blog.example.org",
                    "mapper": f"ldap-roles-{APP}-blog.example.org",
                    "filter": f"(&(objectClass=groupOfNames)(cn={APP}-blog.example.org-*))",
                },
                {
                    "tenant": "shop.example.org",
                    "mapper": f"ldap-roles-{APP}-shop.example.org",
                    "filter": f"(&(objectClass=groupOfNames)(cn={APP}-shop.example.org-*))",
                },
            ],
        )

    def test_tenant_aware_app_without_global_roles_maps_only_containers(self):
        apps = {
            APP: {
                "rbac": {"tenancy": {"axis": "domain"}, "roles": {"editor": {}}},
                "domains": {"canonical": ["blog.example.org"]},
            }
        }
        self.assertEqual(
            self.scopes(apps, APP)["filter"],
            f"(&(objectClass=groupOfNames)(cn={APP}-blog.example.org))",
        )


if __name__ == "__main__":
    unittest.main()
