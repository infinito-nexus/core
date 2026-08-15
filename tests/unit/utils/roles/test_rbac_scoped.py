"""The application-scoped role boundary.

``mcp`` grants reach whatever the deployment issued the provider's credentials
for, not the caller's own data, so holding it on one application must never
imply holding it on another. ``APPLICATION_SCOPED_ROLES`` is what keeps an
unscoped ``roles: [mcp]`` from becoming every deployed application at once, and
the Keycloak realm builder, the LDAP entry builder and the Open WebUI reconciler
all resolve membership through this one module.
"""

from __future__ import annotations

import unittest
from typing import ClassVar

from utils.roles.rbac.scoped import (
    APPLICATION_SCOPED_ROLES,
    granted_roles,
    members_with_role,
)


class TestGrantedRoles(unittest.TestCase):
    def test_a_scoped_grant_reaches_only_the_named_application(self) -> None:
        user = {"application_roles": {"web-app-baserow": ["mcp"]}}
        self.assertEqual({"mcp", "mcp-reader"}, granted_roles(user, "web-app-baserow"))
        self.assertEqual(set(), granted_roles(user, "web-app-n8n"))

    def test_an_unscoped_scoped_role_grants_nothing_anywhere(self) -> None:
        user = {"roles": ["mcp"]}
        for application_id in ("web-app-baserow", "web-app-n8n"):
            with self.subTest(application_id=application_id):
                self.assertEqual(set(), granted_roles(user, application_id))

    def test_an_unscoped_ordinary_role_reaches_every_application(self) -> None:
        user = {"roles": ["administrator"]}
        for application_id in ("web-app-baserow", "web-app-n8n"):
            with self.subTest(application_id=application_id):
                self.assertEqual({"administrator"}, granted_roles(user, application_id))

    def test_scoped_and_unscoped_grants_combine_on_the_named_application(self) -> None:
        user = {
            "roles": ["administrator"],
            "application_roles": {"web-app-baserow": ["mcp"]},
        }
        self.assertEqual(
            {"administrator", "mcp", "mcp-reader"},
            granted_roles(user, "web-app-baserow"),
        )
        self.assertEqual({"administrator"}, granted_roles(user, "web-app-n8n"))

    def test_two_applications_carry_independent_scoped_grants(self) -> None:
        user = {
            "application_roles": {
                "web-app-baserow": ["mcp"],
                "web-app-n8n": ["administrator"],
            }
        }
        self.assertEqual({"mcp", "mcp-reader"}, granted_roles(user, "web-app-baserow"))
        self.assertEqual({"administrator"}, granted_roles(user, "web-app-n8n"))

    def test_a_user_without_any_declaration_holds_nothing(self) -> None:
        self.assertEqual(set(), granted_roles({}, "web-app-baserow"))

    def test_null_declarations_are_treated_as_empty(self) -> None:
        user = {"roles": None, "application_roles": None}
        self.assertEqual(set(), granted_roles(user, "web-app-baserow"))

    def test_a_legacy_mcp_grant_confers_reading_not_writing(self) -> None:
        user = {"application_roles": {"web-app-baserow": ["mcp"]}}
        granted = granted_roles(user, "web-app-baserow")
        self.assertIn("mcp-reader", granted)
        self.assertNotIn("mcp-writer", granted)

    def test_an_explicit_writer_grant_is_kept(self) -> None:
        user = {"application_roles": {"web-app-baserow": ["mcp-writer"]}}
        self.assertEqual({"mcp-writer"}, granted_roles(user, "web-app-baserow"))

    def test_mcp_is_application_scoped(self) -> None:
        self.assertIn("mcp", APPLICATION_SCOPED_ROLES)


class TestMembersWithRole(unittest.TestCase):
    USERS: ClassVar[dict] = {
        "biber": {"application_roles": {"web-app-baserow": ["mcp"]}},
        "otter": {"roles": ["mcp"]},
        "admin": {"roles": ["administrator"]},
    }

    def test_only_the_scoped_holder_is_a_member(self) -> None:
        self.assertEqual(
            ["biber"], members_with_role(self.USERS, "web-app-baserow", "mcp-reader")
        )

    def test_the_unscoped_holder_is_a_member_of_no_application(self) -> None:
        self.assertEqual([], members_with_role(self.USERS, "web-app-n8n", "mcp"))

    def test_the_declared_username_wins_over_the_key(self) -> None:
        users = {
            "biber": {
                "username": "biber@infinito.example",
                "application_roles": {"web-app-baserow": ["mcp"]},
            }
        }
        self.assertEqual(
            ["biber@infinito.example"],
            members_with_role(users, "web-app-baserow", "mcp-reader"),
        )

    def test_members_are_sorted_so_the_grant_diff_is_stable(self) -> None:
        users = {
            name: {"application_roles": {"web-app-baserow": ["mcp"]}}
            for name in ("otter", "biber", "adler")
        }
        self.assertEqual(
            ["adler", "biber", "otter"],
            members_with_role(users, "web-app-baserow", "mcp-reader"),
        )

    def test_no_users_yields_no_members(self) -> None:
        self.assertEqual([], members_with_role(None, "web-app-baserow", "mcp"))

    def test_a_null_user_entry_does_not_abort_the_scan(self) -> None:
        users = {"ghost": None, "biber": {"application_roles": {"app": ["mcp"]}}}
        self.assertEqual(["biber"], members_with_role(users, "app", "mcp-reader"))


class TestMcpRoleVocabulary(unittest.TestCase):
    def test_both_mcp_roles_are_application_scoped(self) -> None:
        from utils.roles.rbac.scoped import APPLICATION_SCOPED_ROLES, MCP_ROLES

        for role in MCP_ROLES:
            self.assertIn(role, APPLICATION_SCOPED_ROLES)

    def test_a_writer_grant_does_not_confer_the_reader_name(self) -> None:
        user = {"application_roles": {"app": ["mcp-writer"]}}
        self.assertEqual({"mcp-writer"}, granted_roles(user, "app"))


if __name__ == "__main__":
    unittest.main()
