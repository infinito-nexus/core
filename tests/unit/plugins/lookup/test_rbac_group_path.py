import unittest

from ansible.errors import AnsibleError
from plugins.lookup.rbac_group_path import LookupModule


def _vars(applications, rbac_group_name="roles"):
    return {
        "applications": applications,
        "RBAC": {"GROUP": {"NAME": rbac_group_name}},
    }


class TestRbacGroupPathLookup(unittest.TestCase):
    def setUp(self):
        self.lookup = LookupModule()
        self.non_tenant_apps = {
            "web-app-yourls": {
                "rbac": {
                    "roles": {
                        "administrator": {"description": "Admin"},
                    }
                }
            },
            "web-app-gitea": {
                "rbac": {
                    "roles": {
                        "editor": {"description": "Editor"},
                    }
                }
            },
        }
        self.tenant_apps = {
            "web-app-wordpress": {
                "rbac": {
                    "tenancy": {"axis": "domain", "source": "server.domains.canonical"},
                    "roles": {
                        "editor": {"description": "Editor"},
                        "subscriber": {"description": "Subscriber"},
                        "network-administrator": {
                            "description": "Network admin",
                            "scope": "global",
                        },
                    },
                }
            }
        }

    # --- non-tenant apps -----------------------------------------------------

    def test_non_tenant_app_declared_role(self):
        result = self.lookup.run(
            [],
            variables=_vars(self.non_tenant_apps),
            application_id="web-app-yourls",
            role="administrator",
        )
        self.assertEqual(result, ["roles/web-app-yourls/administrator"])

    def test_non_tenant_app_declared_non_admin_role(self):
        result = self.lookup.run(
            [],
            variables=_vars(self.non_tenant_apps),
            application_id="web-app-gitea",
            role="editor",
        )
        self.assertEqual(result, ["roles/web-app-gitea/editor"])

    def test_non_tenant_app_implicit_administrator_always_valid(self):
        # Even if an app does not explicitly declare administrator in its
        # rbac.roles, requirement 004 auto-adds it; the lookup MUST accept
        # that without failing.
        apps = {
            "web-app-gitea": {
                "rbac": {
                    "roles": {
                        "editor": {"description": "Editor"},
                    }
                }
            }
        }
        result = self.lookup.run(
            [],
            variables=_vars(apps),
            application_id="web-app-gitea",
            role="administrator",
        )
        self.assertEqual(result, ["roles/web-app-gitea/administrator"])

    def test_non_tenant_app_tenant_argument_rejected(self):
        with self.assertRaises(AnsibleError) as cm:
            self.lookup.run(
                [],
                variables=_vars(self.non_tenant_apps),
                application_id="web-app-yourls",
                role="administrator",
                tenant="blog.example",
            )
        self.assertIn("global", str(cm.exception))

    # --- tenant-aware apps ---------------------------------------------------

    def test_tenant_aware_per_tenant_role_requires_tenant(self):
        with self.assertRaises(AnsibleError) as cm:
            self.lookup.run(
                [],
                variables=_vars(self.tenant_apps),
                application_id="web-app-wordpress",
                role="editor",
            )
        self.assertIn("tenant-scoped", str(cm.exception).lower() + " tenant")

    def test_tenant_aware_per_tenant_role_with_tenant(self):
        result = self.lookup.run(
            [],
            variables=_vars(self.tenant_apps),
            application_id="web-app-wordpress",
            role="editor",
            tenant="blog.example",
        )
        self.assertEqual(result, ["roles/web-app-wordpress/blog.example/editor"])

    def test_tenant_aware_global_scope_role_rejects_tenant(self):
        with self.assertRaises(AnsibleError) as cm:
            self.lookup.run(
                [],
                variables=_vars(self.tenant_apps),
                application_id="web-app-wordpress",
                role="network-administrator",
                tenant="blog.example",
            )
        self.assertIn("global", str(cm.exception))

    def test_tenant_aware_global_scope_role_without_tenant(self):
        result = self.lookup.run(
            [],
            variables=_vars(self.tenant_apps),
            application_id="web-app-wordpress",
            role="network-administrator",
        )
        self.assertEqual(result, ["roles/web-app-wordpress/network-administrator"])

    def test_tenant_is_lowercased(self):
        result = self.lookup.run(
            [],
            variables=_vars(self.tenant_apps),
            application_id="web-app-wordpress",
            role="editor",
            tenant="Blog.EXAMPLE",
        )
        self.assertEqual(result, ["roles/web-app-wordpress/blog.example/editor"])

    # --- failure modes -------------------------------------------------------

    def test_unknown_role_fails(self):
        with self.assertRaises(AnsibleError) as cm:
            self.lookup.run(
                [],
                variables=_vars(self.non_tenant_apps),
                application_id="web-app-yourls",
                role="not-declared",
            )
        msg = str(cm.exception)
        self.assertIn("not-declared", msg)

    def test_unknown_application_id_fails(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(
                [],
                variables=_vars(self.non_tenant_apps),
                application_id="web-app-does-not-exist",
                role="administrator",
            )

    def test_missing_rbac_group_name_fails(self):
        with self.assertRaises(AnsibleError) as cm:
            self.lookup.run(
                [],
                variables={"applications": self.non_tenant_apps, "RBAC": {}},
                application_id="web-app-yourls",
                role="administrator",
            )
        self.assertIn("RBAC.GROUP.NAME", str(cm.exception))

    def test_positional_arguments_rejected(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(
                ["web-app-yourls", "administrator"],
                variables=_vars(self.non_tenant_apps),
            )

    def test_custom_rbac_group_name(self):
        result = self.lookup.run(
            [],
            variables=_vars(self.non_tenant_apps, rbac_group_name="infinito-roles"),
            application_id="web-app-yourls",
            role="administrator",
        )
        self.assertEqual(result, ["infinito-roles/web-app-yourls/administrator"])


if __name__ == "__main__":
    unittest.main()
