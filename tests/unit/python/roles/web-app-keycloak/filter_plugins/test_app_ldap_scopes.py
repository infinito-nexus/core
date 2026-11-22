"""Unit tests for ``kc_app_ldap_scopes`` in ``build_realm_rbac_groups.py``."""

from __future__ import annotations

import fnmatch
import importlib.util
import re
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


def _matches(ldap_filter, cn):
    """Tell whether a group with this ``cn`` passes the filter's ``cn`` clauses.

    Args:
        ldap_filter: filter as built by ``kc_app_ldap_scopes``, whose ``cn``
            clauses are alternatives.
        cn: common name of the LDAP group entry.

    Returns:
        True when any ``(cn=...)`` clause matches, ``*`` as a wildcard.
    """
    return any(
        fnmatch.fnmatchcase(cn, pattern)
        for pattern in re.findall(r"\(cn=([^)]*)\)", ldap_filter)
    )


class TestAppLdapScopes(unittest.TestCase):
    def setUp(self):
        self.scopes = _load()

    def test_tenant_unaware_app_matches_each_role_group_exactly(self):
        apps = {APP: {"rbac": {"roles": {"editor": {}}}}}
        self.assertEqual(
            self.scopes(apps, APP),
            {
                "filter": f"(&(objectClass=groupOfNames)(|(cn={APP}-administrator)(cn={APP}-editor)))",
                "tenants": [],
            },
        )

    def test_tenant_unaware_app_without_roles_maps_its_administrator_group(self):
        apps = {APP: {"rbac": {}}}
        self.assertEqual(
            self.scopes(apps, APP)["filter"],
            f"(&(objectClass=groupOfNames)(cn={APP}-administrator))",
        )

    def test_prefix_sharing_apps_never_map_each_others_groups(self):
        apps = {
            "svc-net-tor": {"rbac": {"roles": {}}},
            "svc-net-tor-smtp": {"rbac": {"roles": {}}},
        }
        groups = ["svc-net-tor-administrator", "svc-net-tor-smtp-administrator"]
        for app_id, owned in zip(apps, groups, strict=True):
            with self.subTest(app=app_id):
                ldap_filter = self.scopes(apps, app_id)["filter"]
                self.assertEqual(
                    [cn for cn in groups if _matches(ldap_filter, cn)], [owned]
                )

    def test_matcher_flags_the_overlap_of_a_prefix_filter(self):
        prefix_filter = "(&(objectClass=groupOfNames)(cn=svc-net-tor-*))"
        self.assertTrue(_matches(prefix_filter, "svc-net-tor-smtp-administrator"))

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
