import importlib.util
import unittest
from pathlib import Path
from typing import ClassVar

current_dir = str(Path(__file__).parent)
filter_plugin_path = str(
    Path(
        str(Path(current_dir) / "../../../../roles/web-app-keycloak/filter_plugins")
    ).resolve()
)

spec = importlib.util.spec_from_file_location(
    "build_realm_rbac_groups",
    str(Path(filter_plugin_path) / "build_realm_rbac_groups.py"),
)
brg_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brg_module)

build_realm_rbac_groups = brg_module.build_realm_rbac_groups


def _by_path(groups):
    return {g["path"]: g["members"] for g in groups}


class TestBuildRealmRbacGroupsNonTenant(unittest.TestCase):
    def setUp(self):
        self.applications = {
            "web-app-prometheus": {"rbac": {}},
            "web-app-wordpress": {
                "rbac": {
                    "roles": {
                        "editor": {"description": "Can edit content"},
                        "viewer": {"description": "Can view content"},
                    }
                }
            },
        }
        self.users = {
            "administrator": {"roles": ["administrator"], "password": "pw"},
            "alice": {"roles": ["editor"], "password": "pw"},
            "biber": {"roles": [], "password": "pw"},
        }

    def test_implicit_admin_group_for_rbac_app_without_roles(self):
        groups = _by_path(
            build_realm_rbac_groups(self.applications, self.users, "roles")
        )
        self.assertIn("roles/web-app-prometheus/administrator", groups)
        self.assertEqual(
            groups["roles/web-app-prometheus/administrator"], ["administrator"]
        )

    def test_declared_roles_and_membership(self):
        groups = _by_path(
            build_realm_rbac_groups(self.applications, self.users, "roles")
        )
        self.assertEqual(groups["roles/web-app-wordpress/editor"], ["alice"])
        self.assertEqual(groups["roles/web-app-wordpress/viewer"], [])
        self.assertEqual(
            groups["roles/web-app-wordpress/administrator"], ["administrator"]
        )

    def test_group_root_is_trimmed(self):
        groups = _by_path(
            build_realm_rbac_groups(self.applications, self.users, "/roles/")
        )
        self.assertIn("roles/web-app-prometheus/administrator", groups)

    def test_group_names_filters_deployed_apps(self):
        groups = _by_path(
            build_realm_rbac_groups(
                self.applications,
                self.users,
                "roles",
                group_names=["web-app-prometheus"],
            )
        )
        self.assertIn("roles/web-app-prometheus/administrator", groups)
        self.assertNotIn("roles/web-app-wordpress/editor", groups)

    def test_non_dict_applications_raises(self):
        from ansible.errors import AnsibleFilterError

        with self.assertRaises(AnsibleFilterError):
            build_realm_rbac_groups([], self.users, "roles")

    def test_empty_group_root_raises(self):
        from ansible.errors import AnsibleFilterError

        with self.assertRaises(AnsibleFilterError):
            build_realm_rbac_groups(self.applications, self.users, "/")

    def test_reserved_and_passwordless_users_are_not_members(self):
        users = {
            "administrator": {"roles": ["administrator"], "password": "pw"},
            "root-like": {
                "roles": ["administrator"],
                "password": "pw",
                "reserved": True,
            },
            "ghost": {"roles": ["administrator"]},
            "nulled": {"roles": ["administrator"], "password": None},
        }
        groups = _by_path(build_realm_rbac_groups(self.applications, users, "roles"))
        self.assertEqual(
            groups["roles/web-app-prometheus/administrator"], ["administrator"]
        )

    def test_member_uses_username_attribute_over_dict_key(self):
        users = {
            "zammad-wizard-bypass-admin": {
                "roles": ["administrator"],
                "password": "pw",
                "username": "wizard-bypass-admin",
            },
        }
        groups = _by_path(build_realm_rbac_groups(self.applications, users, "roles"))
        self.assertEqual(
            groups["roles/web-app-prometheus/administrator"],
            ["wizard-bypass-admin"],
        )


class TestBuildRealmRbacGroupsTenant(unittest.TestCase):
    def setUp(self):
        self.applications = {
            "web-app-wordpress": {
                "domains": {"canonical": ["blog.example", "shop.example"]},
                "rbac": {
                    "tenancy": {"axis": "domain"},
                    "roles": {
                        "editor": {"description": "Per-tenant editor"},
                        "network-administrator": {
                            "description": "Global",
                            "scope": "global",
                        },
                    },
                },
            }
        }
        self.users = {
            "administrator": {"roles": ["administrator"], "password": "pw"},
            "alice": {"roles": ["editor"], "password": "pw"},
        }

    def test_per_tenant_role_emits_one_group_per_tenant(self):
        groups = _by_path(
            build_realm_rbac_groups(self.applications, self.users, "roles")
        )
        self.assertEqual(
            groups["roles/web-app-wordpress/blog.example/editor"], ["alice"]
        )
        self.assertEqual(
            groups["roles/web-app-wordpress/shop.example/editor"], ["alice"]
        )

    def test_implicit_admin_is_per_tenant_in_tenant_app(self):
        groups = _by_path(
            build_realm_rbac_groups(self.applications, self.users, "roles")
        )
        self.assertIn("roles/web-app-wordpress/blog.example/administrator", groups)
        self.assertIn("roles/web-app-wordpress/shop.example/administrator", groups)
        self.assertNotIn("roles/web-app-wordpress/administrator", groups)

    def test_global_scope_role_ignores_tenants(self):
        groups = _by_path(
            build_realm_rbac_groups(self.applications, self.users, "roles")
        )
        self.assertIn("roles/web-app-wordpress/network-administrator", groups)
        self.assertNotIn(
            "roles/web-app-wordpress/blog.example/network-administrator", groups
        )


class TestApplicationScopedRoles(unittest.TestCase):
    """``mcp`` is granted per application, never by the unscoped role list."""

    APPLICATIONS: ClassVar[dict] = {
        "web-app-baserow": {"rbac": {"roles": {"mcp": {"description": "MCP"}}}},
        "web-app-zammad": {"rbac": {"roles": {"mcp": {"description": "MCP"}}}},
    }

    def _groups(self, users):
        return _by_path(build_realm_rbac_groups(self.APPLICATIONS, users, "roles"))

    def test_one_of_many_grants_only_the_named_application(self):
        groups = self._groups(
            {
                "alice": {
                    "roles": [],
                    "password": "pw",
                    "application_roles": {"web-app-baserow": ["mcp"]},
                }
            }
        )
        self.assertEqual(groups["roles/web-app-baserow/mcp"], ["alice"])
        self.assertEqual(groups["roles/web-app-zammad/mcp"], [])

    def test_several_applications_can_be_granted_independently(self):
        groups = self._groups(
            {
                "alice": {
                    "roles": [],
                    "password": "pw",
                    "application_roles": {
                        "web-app-baserow": ["mcp"],
                        "web-app-zammad": ["mcp"],
                    },
                }
            }
        )
        self.assertEqual(groups["roles/web-app-baserow/mcp"], ["alice"])
        self.assertEqual(groups["roles/web-app-zammad/mcp"], ["alice"])

    def test_no_membership_grants_nothing(self):
        groups = self._groups({"biber": {"roles": [], "password": "pw"}})
        self.assertEqual(groups["roles/web-app-baserow/mcp"], [])
        self.assertEqual(groups["roles/web-app-zammad/mcp"], [])

    def test_wrong_application_grants_nothing_here(self):
        groups = self._groups(
            {
                "alice": {
                    "roles": [],
                    "password": "pw",
                    "application_roles": {"web-app-nextcloud": ["mcp"]},
                }
            }
        )
        self.assertEqual(groups["roles/web-app-baserow/mcp"], [])
        self.assertEqual(groups["roles/web-app-zammad/mcp"], [])

    def test_unscoped_mcp_role_grants_no_application(self):
        groups = self._groups({"alice": {"roles": ["mcp"], "password": "pw"}})
        self.assertEqual(groups["roles/web-app-baserow/mcp"], [])
        self.assertEqual(groups["roles/web-app-zammad/mcp"], [])

    def test_removing_the_last_grant_empties_every_group(self):
        granted = {
            "alice": {
                "roles": [],
                "password": "pw",
                "application_roles": {"web-app-baserow": ["mcp"]},
            }
        }
        self.assertEqual(self._groups(granted)["roles/web-app-baserow/mcp"], ["alice"])
        revoked = {"alice": {"roles": [], "password": "pw", "application_roles": {}}}
        self.assertEqual(self._groups(revoked)["roles/web-app-baserow/mcp"], [])

    def test_unscoped_roles_other_than_mcp_are_untouched(self):
        applications = {"web-app-baserow": {"rbac": {"roles": {"editor": {}}}}}
        groups = _by_path(
            build_realm_rbac_groups(
                applications,
                {"alice": {"roles": ["editor"], "password": "pw"}},
                "roles",
            )
        )
        self.assertEqual(groups["roles/web-app-baserow/editor"], ["alice"])


if __name__ == "__main__":
    unittest.main()
