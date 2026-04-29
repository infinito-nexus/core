import unittest
import os
import importlib.util

current_dir = os.path.dirname(__file__)
filter_plugin_path = os.path.abspath(
    os.path.join(current_dir, "../../../../roles/svc-db-openldap/filter_plugins")
)

spec = importlib.util.spec_from_file_location(
    "build_ldap_role_entries",
    os.path.join(filter_plugin_path, "build_ldap_role_entries.py"),
)
ble_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ble_module)

build_ldap_role_entries = ble_module.build_ldap_role_entries


LDAP_FIXTURE = {
    "DN": {
        "OU": {
            "USERS": "ou=users,dc=example,dc=org",
            "ROLES": "ou=roles,dc=example,dc=org",
        }
    },
    "USER": {"ATTRIBUTES": {"ID": "uid"}},
    "RBAC": {
        "FLAVORS": ["groupOfNames"],
        "EMPTY_MEMBER_DN": "cn=__placeholder__,ou=system,dc=example,dc=org",
    },
}


class TestBuildLdapRoleEntriesNonTenant(unittest.TestCase):
    """Flat-DN layout: every group entry is a direct child of ou=roles.
    Parent-child relationship is encoded in the `member` attribute."""

    def setUp(self):
        self.applications = {
            "app1": {
                "group_id": 10000,
                "rbac": {
                    "roles": {
                        "editor": {"description": "Can edit content"},
                        "viewer": {"description": "Can view content"},
                    }
                },
            }
        }
        self.users = {
            "alice": {"roles": ["editor", "administrator"]},
            "bob": {"roles": ["viewer"]},
            "carol": {"roles": []},
        }
        self.ldap = LDAP_FIXTURE

    def test_app_container_is_flat_groupofnames(self):
        entries = build_ldap_role_entries(self.applications, self.users, self.ldap)
        self.assertIn("cn=app1,ou=roles,dc=example,dc=org", entries)
        container = entries["cn=app1,ou=roles,dc=example,dc=org"]
        self.assertIn("groupOfNames", container["objectClass"])
        self.assertEqual(container["description"], "app1")
        for role in ("editor", "viewer", "administrator"):
            child_dn = f"cn=app1-{role},ou=roles,dc=example,dc=org"
            self.assertIn(child_dn, container["member"])

    def test_role_groups_are_flat_but_namespaced_by_cn(self):
        entries = build_ldap_role_entries(self.applications, self.users, self.ldap)
        dns = set(entries.keys())
        self.assertIn("cn=app1-editor,ou=roles,dc=example,dc=org", dns)
        self.assertIn("cn=app1-viewer,ou=roles,dc=example,dc=org", dns)
        self.assertIn("cn=app1-administrator,ou=roles,dc=example,dc=org", dns)

    def test_role_group_description_is_role_name(self):
        entries = build_ldap_role_entries(self.applications, self.users, self.ldap)
        editor = entries["cn=app1-editor,ou=roles,dc=example,dc=org"]
        self.assertEqual(editor["description"], "editor")
        self.assertIn("uid=alice,ou=users,dc=example,dc=org", editor["member"])

    def test_user_without_role_not_in_any_role_group(self):
        entries = build_ldap_role_entries(self.applications, self.users, self.ldap)
        for dn, entry in entries.items():
            if dn.startswith("cn=app1,"):
                continue
            if dn.endswith("-viewer,ou=roles,dc=example,dc=org"):
                self.assertNotIn(
                    "uid=carol,ou=users,dc=example,dc=org",
                    entry.get("member", []),
                )


class TestBuildLdapRoleEntriesTenantAware(unittest.TestCase):
    """Tenant-aware apps produce tenant containers and per-tenant role
    groups, all at the flat ou=roles level. Parent-child via `member`
    refs. description attribute holds the final path segment so Keycloak
    (with group.name.ldap.attribute=description) renders them as
    /roles/<app>/<tenant>/<role> paths."""

    def setUp(self):
        self.applications = {
            "web-app-wordpress": {
                "group_id": 10001,
                "server": {"domains": {"canonical": ["blog.example", "shop.example"]}},
                "rbac": {
                    "tenancy": {"axis": "domain"},
                    "roles": {
                        "editor": {"description": "Editor"},
                        "subscriber": {"description": "Subscriber"},
                        "network-administrator": {
                            "description": "Network admin",
                            "scope": "global",
                        },
                    },
                },
            }
        }
        self.users = {"alice": {"roles": ["editor"]}}

    def test_app_container_references_tenants_and_global_roles(self):
        entries = build_ldap_role_entries(self.applications, self.users, LDAP_FIXTURE)
        container = entries["cn=web-app-wordpress,ou=roles,dc=example,dc=org"]
        self.assertEqual(container["description"], "web-app-wordpress")
        members = container["member"]
        self.assertIn(
            "cn=web-app-wordpress-blog.example,ou=roles,dc=example,dc=org", members
        )
        self.assertIn(
            "cn=web-app-wordpress-shop.example,ou=roles,dc=example,dc=org", members
        )
        self.assertIn(
            "cn=web-app-wordpress-network-administrator,ou=roles,dc=example,dc=org",
            members,
        )

    def test_tenant_containers_hold_per_tenant_role_refs(self):
        entries = build_ldap_role_entries(self.applications, self.users, LDAP_FIXTURE)
        for tenant in ("blog.example", "shop.example"):
            tenant_dn = f"cn=web-app-wordpress-{tenant},ou=roles,dc=example,dc=org"
            self.assertIn(tenant_dn, entries)
            tenant_entry = entries[tenant_dn]
            self.assertEqual(tenant_entry["description"], tenant)
            for role in ("editor", "subscriber", "administrator"):
                self.assertIn(
                    f"cn=web-app-wordpress-{tenant}-{role},ou=roles,dc=example,dc=org",
                    tenant_entry["member"],
                )

    def test_per_tenant_role_groups_exist_at_flat_level(self):
        entries = build_ldap_role_entries(self.applications, self.users, LDAP_FIXTURE)
        dns = set(entries.keys())
        for tenant in ("blog.example", "shop.example"):
            for role in ("editor", "subscriber", "administrator"):
                self.assertIn(
                    f"cn=web-app-wordpress-{tenant}-{role},ou=roles,dc=example,dc=org",
                    dns,
                )

    def test_global_scope_role_lives_at_app_level_not_tenant(self):
        entries = build_ldap_role_entries(self.applications, self.users, LDAP_FIXTURE)
        dns = set(entries.keys())
        self.assertIn(
            "cn=web-app-wordpress-network-administrator,ou=roles,dc=example,dc=org",
            dns,
        )
        for tenant in ("blog.example", "shop.example"):
            self.assertNotIn(
                f"cn=web-app-wordpress-{tenant}-network-administrator,"
                f"ou=roles,dc=example,dc=org",
                dns,
            )

    def test_canonical_domain_case_normalised(self):
        self.applications["web-app-wordpress"]["server"]["domains"]["canonical"] = [
            "Blog.EXAMPLE"
        ]
        entries = build_ldap_role_entries(self.applications, self.users, LDAP_FIXTURE)
        dns = set(entries.keys())
        self.assertIn(
            "cn=web-app-wordpress-blog.example-editor,ou=roles,dc=example,dc=org",
            dns,
        )


class TestBuildLdapRoleEntriesGroupNamesGate(unittest.TestCase):
    def setUp(self):
        self.applications = {
            "web-app-wordpress": {
                "group_id": 10001,
                "rbac": {"roles": {"editor": {"description": "Editor"}}},
            },
            "web-app-pretix": {
                "group_id": 10002,
                "rbac": {"roles": {"organizer": {"description": "Organizer"}}},
            },
        }
        self.users = {"alice": {"roles": ["editor"]}}

    def test_only_deployed_apps_contribute_when_group_names_given(self):
        entries = build_ldap_role_entries(
            self.applications,
            self.users,
            LDAP_FIXTURE,
            group_names=["web-app-wordpress"],
        )
        dns = set(entries.keys())
        self.assertIn("cn=web-app-wordpress,ou=roles,dc=example,dc=org", dns)
        self.assertIn("cn=web-app-wordpress-editor,ou=roles,dc=example,dc=org", dns)
        self.assertIn(
            "cn=web-app-wordpress-administrator,ou=roles,dc=example,dc=org", dns
        )
        for d in dns:
            self.assertNotIn("web-app-pretix", d)

    def test_empty_group_names_emits_no_entries(self):
        entries = build_ldap_role_entries(
            self.applications, self.users, LDAP_FIXTURE, group_names=[]
        )
        self.assertEqual(entries, {})

    def test_group_names_none_preserves_legacy_behavior(self):
        entries = build_ldap_role_entries(
            self.applications, self.users, LDAP_FIXTURE, group_names=None
        )
        dns = set(entries.keys())
        self.assertIn("cn=web-app-wordpress-editor,ou=roles,dc=example,dc=org", dns)
        self.assertIn("cn=web-app-pretix-organizer,ou=roles,dc=example,dc=org", dns)


if __name__ == "__main__":
    unittest.main()
