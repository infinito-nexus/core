from __future__ import annotations

import unittest

from utils.roles.rbac.catalogue import (
    access_catalogue,
    approver_grants,
    delegated_groups,
    is_administrator_role,
)

APPLICATIONS = {
    "web-app-blog": {
        "rbac": {
            "roles": {
                "subscriber": {"description": "Reads posts"},
                "editor": {"description": "Publishes posts"},
                "administrator": {"description": "Runs the blog"},
            }
        }
    },
    "web-app-agent": {"rbac": {"roles": {"mcp": {"description": "Drives MCP"}}}},
    "web-app-vault": {"rbac": {}},
    "web-app-multi": {
        "domains": {"canonical": ["A.example/", "b.example"]},
        "rbac": {
            "tenancy": {"axis": "domain"},
            "roles": {
                "author": {"description": "Writes"},
                "network-administrator": {"description": "Runs all", "scope": "global"},
            },
        },
    },
}


class TestAccessCatalogue(unittest.TestCase):
    def setUp(self):
        self.catalogue = access_catalogue(
            APPLICATIONS, [*APPLICATIONS, "web-app-unknown"], "roles"
        )

    def test_roles_keep_their_declaration_order_and_descriptions(self):
        roles = self.catalogue["web-app-blog"]["roles"]

        self.assertEqual(
            ["subscriber", "editor", "administrator"], [r["id"] for r in roles]
        )
        self.assertEqual("Publishes posts", roles[1]["description"])
        self.assertEqual("/roles/web-app-blog/editor", roles[1]["path"])

    def test_the_first_non_administrator_role_is_the_default(self):
        self.assertEqual("subscriber", self.catalogue["web-app-blog"]["default"])

    def test_the_implicit_administrator_is_appended_and_marked(self):
        roles = self.catalogue["web-app-agent"]["roles"]

        self.assertEqual(["mcp", "administrator"], [r["id"] for r in roles])
        self.assertEqual([False, True], [r["administrator"] for r in roles])

    def test_an_application_with_only_an_administrator_has_no_default(self):
        self.assertIsNone(self.catalogue["web-app-vault"]["default"])

    def test_per_tenant_roles_expand_per_canonical_domain(self):
        ids = [r["id"] for r in self.catalogue["web-app-multi"]["roles"]]

        self.assertEqual(
            [
                "a.example/author",
                "b.example/author",
                "network-administrator",
                "a.example/administrator",
                "b.example/administrator",
            ],
            ids,
        )

    def test_an_application_missing_from_the_payload_is_skipped(self):
        self.assertNotIn("web-app-unknown", self.catalogue)

    def test_an_unknown_axis_is_refused(self):
        with self.assertRaises(ValueError):
            access_catalogue(
                {"web-app-x": {"rbac": {"tenancy": {"axis": "planet"}}}},
                ["web-app-x"],
                "roles",
            )

    def test_administrator_roles_are_recognised_by_name(self):
        self.assertTrue(is_administrator_role("administrator"))
        self.assertTrue(is_administrator_role("network-administrator"))
        self.assertFalse(is_administrator_role("administrators-friend"))

    def test_a_role_carrying_realm_management_roles_is_an_administrator_role(self):
        catalogue = access_catalogue(
            {
                "web-app-idp": {
                    "rbac": {
                        "roles": {
                            "user-manager": {
                                "description": "Manages users",
                                "realm_management": ["manage-users"],
                            },
                            "viewer": {"description": "Views", "realm_management": []},
                        }
                    }
                }
            },
            ["web-app-idp"],
            "roles",
        )

        flags = {r["id"]: r["administrator"] for r in catalogue["web-app-idp"]["roles"]}
        self.assertEqual(
            {"user-manager": True, "viewer": False, "administrator": True}, flags
        )
        self.assertEqual("viewer", catalogue["web-app-idp"]["default"])


class TestDelegatedGroups(unittest.TestCase):
    def test_an_application_administrator_may_grant_only_non_administrator_roles(self):
        delegations = {
            d["application"]: d
            for d in delegated_groups(
                access_catalogue(APPLICATIONS, list(APPLICATIONS), "roles")
            )
        }

        self.assertEqual(
            "/roles/web-app-blog/administrator", delegations["web-app-blog"]["approver"]
        )
        self.assertEqual(
            ["/roles/web-app-blog/subscriber", "/roles/web-app-blog/editor"],
            delegations["web-app-blog"]["groups"],
        )
        self.assertNotIn("web-app-vault", delegations)

    def test_a_tenant_aware_application_without_a_global_administrator_delegates_nothing(
        self,
    ):
        delegations = delegated_groups(
            access_catalogue(APPLICATIONS, ["web-app-multi"], "roles")
        )

        self.assertEqual([], delegations)


class TestApproverGrants(unittest.TestCase):
    PLATFORM = "/roles/web-svc-access-request/administrator"

    def setUp(self):
        self.grants = approver_grants(
            access_catalogue(APPLICATIONS, list(APPLICATIONS), "roles"), self.PLATFORM
        )

    def test_the_platform_group_comes_first_and_may_grant_every_role_group(self):
        platform = self.grants[0]

        self.assertEqual(self.PLATFORM, platform["approver"])
        self.assertIn("/roles/web-app-blog/administrator", platform["groups"])
        self.assertIn("/roles/web-app-multi/network-administrator", platform["groups"])
        self.assertIn("/roles/web-app-vault/administrator", platform["groups"])
        self.assertEqual(sorted(platform["groups"]), platform["groups"])

    def test_an_application_administrator_group_gets_only_its_delegation(self):
        blog = next(
            g
            for g in self.grants
            if g["approver"] == "/roles/web-app-blog/administrator"
        )

        self.assertEqual(
            ["/roles/web-app-blog/subscriber", "/roles/web-app-blog/editor"],
            blog["groups"],
        )

    def test_the_platform_group_is_listed_once_even_when_it_delegates(self):
        catalogue = access_catalogue(
            {"web-svc-access-request": {"rbac": {"roles": {"viewer": {}}}}},
            ["web-svc-access-request"],
            "roles",
        )

        approvers = [g["approver"] for g in approver_grants(catalogue, self.PLATFORM)]

        self.assertEqual([self.PLATFORM], approvers)


if __name__ == "__main__":
    unittest.main()
