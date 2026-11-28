from __future__ import annotations

import json
import unittest

from . import PROJECT_ROOT
from ._fake_frappe import FakeFrappe, run_script

SCRIPT = PROJECT_ROOT / "roles/web-app-erpnext/files/python/apply/ldap_source.py"
ROLES_DN = "ou=roles,dc=example,dc=org"
GRANTS = {
    "/roles/web-app-erpnext/administrator": ["System Manager"],
    "/roles/web-app-erpnext/manager": ["Sales User", "Purchase User"],
    "/roles/web-app-erpnext/customer": ["Customer"],
}
MAPPED_GROUP = "/roles/web-app-consumer/auditor"
GROUP_ROLES = {MAPPED_GROUP: ["Audit Editor"]}
SITE_ROLES = ("System Manager", "Sales User", "Purchase User")


def _env(grants, group_roles):
    return {
        "SITE_NAME": "next.erp.infinito.example",
        "LDAP_HOST": "ldap",
        "LDAP_PORT": "389",
        "LDAP_BASE_DN": "ou=users,dc=example,dc=org",
        "LDAP_ROLES_DN": ROLES_DN,
        "LDAP_BIND_DN": "cn=administrator,dc=example,dc=org",
        "LDAP_BIND_PW": "bind-password",
        "LDAP_UID_ATTR": "uid",
        "LDAP_MAIL_ATTR": "mail",
        "LDAP_FIRSTNAME_ATTR": "givenName",
        "LDAP_SURNAME_ATTR": "sn",
        "LDAP_PHONE_ATTR": "telephoneNumber",
        "LDAP_MOBILE_ATTR": "mobile",
        "LDAP_MEMBER_OF_ATTR": "memberOf",
        "LDAP_GROUP_OBJECTCLASS": "groupOfNames",
        "LDAP_GROUP_MEMBER_ATTR": "member",
        "ROLE_GRANTS_JSON": json.dumps(grants),
        "GROUP_ROLES_JSON": json.dumps(group_roles),
        "LDAP_LOGIN_ENABLED": "true",
    }


class TestLdapSource(unittest.TestCase):
    def setUp(self) -> None:
        self.frappe = FakeFrappe()
        for role in SITE_ROLES:
            self.frappe.seed("Role", role, role_name=role)

    def _run(self, grants=GRANTS, group_roles=GROUP_ROLES):
        return run_script(SCRIPT, self.frappe, _env(grants, group_roles)).splitlines()

    def _settings(self):
        return self.frappe.singles["LDAP Settings"]

    def _rows(self):
        return [
            (row["ldap_group"], row["erpnext_role"])
            for row in self._settings()["ldap_groups"]
        ]

    def test_the_settings_drop_the_role_rows_no_sign_in_reads(self) -> None:
        self.frappe.singles["LDAP Settings"] = {
            "ldap_groups": [
                {"ldap_group": "web-app-erpnext-manager", "erpnext_role": "Sales User"}
            ]
        }

        self.assertEqual(self._run(), [])

        self.assertEqual(self._rows(), [])
        self.assertNotIn("Customer", self.frappe.records["Role"])

    def test_only_members_of_a_role_or_mapped_group_find_their_account(self) -> None:
        self._run()

        members = "".join(
            f"(memberOf=cn={cn},{ROLES_DN})"
            for cn in (
                "web-app-consumer-auditor",
                "web-app-erpnext-administrator",
                "web-app-erpnext-customer",
                "web-app-erpnext-manager",
            )
        )
        self.assertEqual(
            self._settings()["ldap_search_string"], f"(&(uid={{0}})(|{members}))"
        )

    def test_every_spelling_of_one_group_admits_its_members_once(self) -> None:
        self._run(
            {
                "/roles/web-app-erpnext/manager": ["Sales User"],
                "roles/web-app-erpnext/manager/": ["Sales User", "Purchase User"],
            },
            {},
        )

        self.assertEqual(
            self._settings()["ldap_search_string"],
            f"(&(uid={{0}})(|(memberOf=cn=web-app-erpnext-manager,{ROLES_DN})))",
        )

    def test_a_group_path_of_another_shape_fails_before_any_write(self) -> None:
        with self.assertRaises(ValueError):
            self._run({"/roles/web-app-erpnext/t.example/customer": ["Customer"]})

        self.assertNotIn("LDAP Settings", self.frappe.singles)
        self.assertNotIn("Customer", self.frappe.records["Role"])

    def test_a_mapped_group_path_of_another_shape_fails_before_any_write(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            self._run(group_roles={"/roles/web-app-consumer/t.example/auditor": []})

        self.assertNotIn("LDAP Settings", self.frappe.singles)
        self.assertNotIn("Customer", self.frappe.records["Role"])


if __name__ == "__main__":
    unittest.main()
