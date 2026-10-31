from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from . import PROJECT_ROOT
from ._fake_frappe import FakeFrappe, run_script

SCRIPT = PROJECT_ROOT / "roles/web-app-erpnext/files/python/apply/rbac_roles.py"
GRANTS = {
    "administrator": ["System Manager"],
    "manager": ["Sales User", "Purchase User"],
    "customer": ["Customer"],
}
BOT = "erpnext-api-bot@infinito.example"
PLATFORM_ADMIN = "platformadmin@infinito.example"
PROTECTED = ["Administrator", "Guest", BOT, PLATFORM_ADMIN]
NO_MEMBERS = {"administrator": [], "manager": [], "customer": []}
SSO = "keycloak"
DIRECTORY = "directory"
API_USER = "security-check-api@infinito.example"


def _env(members):
    return {
        "SITE_NAME": "next.erp.infinito.example",
        "ROLE_GRANTS_JSON": json.dumps(GRANTS),
        "ROLE_MEMBERS_JSON": json.dumps(members),
        "PROTECTED_USERS_JSON": json.dumps(PROTECTED),
        "SSO_PROVIDER_NAME": SSO,
        "DIRECTORY_PROVIDER_NAME": DIRECTORY,
    }


def _roles(*names):
    return [SimpleNamespace(role=name) for name in names]


def _links(*providers):
    return [
        SimpleNamespace(provider=provider, userid="someone", username="someone")
        for provider in providers
    ]


def _member(username, email):
    return {"username": username, "email": email, "name": username}


class TestRbacRoles(unittest.TestCase):
    def setUp(self) -> None:
        self.frappe = FakeFrappe()
        self.frappe.seed(
            "User", "Administrator", enabled=1, roles=_roles("System Manager")
        )
        self.frappe.seed("User", "Guest", enabled=1, roles=_roles("Guest"))
        self.frappe.seed(
            "User", BOT, email=BOT, enabled=1, roles=_roles("System Manager")
        )

    def _run(self, members=None):
        printed = run_script(
            SCRIPT, self.frappe, _env({**NO_MEMBERS, **(members or {})})
        )
        return printed.splitlines()

    def _user(self, name):
        return self.frappe.records["User"][name]

    def _role_names(self, name):
        return sorted(row.role for row in self._user(name)["roles"])

    def _link_rows(self, name):
        return [
            (row.provider, row.userid, row.username)
            for row in self._user(name)["social_logins"]
        ]

    def _seed_user(self, name, enabled=1, roles=(), links=()):
        self.frappe.seed(
            "User",
            name,
            email=name,
            enabled=enabled,
            roles=_roles(*roles),
            social_logins=_links(*links),
        )

    def test_creates_a_member_with_the_roles_of_its_group(self) -> None:
        output = self._run({"manager": [_member("alice", "Alice@infinito.example")]})

        self.assertEqual(
            output,
            [
                "CHANGED alice@infinito.example created",
                "CHANGED alice@infinito.example linked directory",
                "CHANGED alice@infinito.example granted Purchase User",
                "CHANGED alice@infinito.example granted Sales User",
            ],
        )
        self.assertEqual(self._user("alice@infinito.example")["enabled"], 1)
        self.assertEqual(
            self._role_names("alice@infinito.example"), ["Purchase User", "Sales User"]
        )

    def test_links_a_member_to_the_directory_under_its_username(self) -> None:
        self._seed_user("alice@infinito.example", roles=("Customer",))

        output = self._run({"customer": [_member("alice", "alice@infinito.example")]})

        self.assertEqual(output, ["CHANGED alice@infinito.example linked directory"])
        self.assertEqual(
            self._link_rows("alice@infinito.example"), [(DIRECTORY, "alice", "alice")]
        )

    def test_a_member_linked_by_its_keycloak_sign_in_gets_no_second_link(
        self,
    ) -> None:
        self._seed_user("alice@infinito.example", roles=("Customer",), links=(SSO,))

        output = self._run({"customer": [_member("alice", "alice@infinito.example")]})

        self.assertEqual(output, ["UNCHANGED"])
        self.assertEqual(
            self._link_rows("alice@infinito.example"), [(SSO, "someone", "someone")]
        )

    def test_reenables_a_disabled_member(self) -> None:
        self._seed_user("alice@infinito.example", enabled=0, links=(SSO,))

        output = self._run(
            {"administrator": [_member("alice", "alice@infinito.example")]}
        )

        self.assertEqual(
            output,
            [
                "CHANGED alice@infinito.example enabled",
                "CHANGED alice@infinito.example granted System Manager",
            ],
        )
        self.assertEqual(self._user("alice@infinito.example")["enabled"], 1)
        self.assertEqual(self._role_names("alice@infinito.example"), ["System Manager"])

    def test_withdraws_the_roles_of_a_group_the_member_left(self) -> None:
        self._seed_user(
            "alice@infinito.example",
            roles=("System Manager", "Sales User", "Purchase User", "Blogger"),
            links=(SSO,),
        )

        output = self._run({"manager": [_member("alice", "alice@infinito.example")]})

        self.assertEqual(
            output, ["CHANGED alice@infinito.example revoked System Manager"]
        )
        self.assertEqual(
            self._role_names("alice@infinito.example"),
            ["Blogger", "Purchase User", "Sales User"],
        )

    def test_disables_a_directory_account_outside_every_group_without_a_role(
        self,
    ) -> None:
        self._seed_user("biber@infinito.example", links=(SSO,))

        output = self._run()

        self.assertEqual(output, ["CHANGED biber@infinito.example disabled"])
        self.assertEqual(self._user("biber@infinito.example")["enabled"], 0)

    def test_demotes_and_disables_a_directory_account_with_only_managed_roles(
        self,
    ) -> None:
        self._seed_user(
            "biber@infinito.example", roles=("Sales User",), links=(DIRECTORY,)
        )

        output = self._run()

        self.assertEqual(
            output,
            [
                "CHANGED biber@infinito.example revoked Sales User",
                "CHANGED biber@infinito.example disabled",
            ],
        )
        self.assertEqual(self._role_names("biber@infinito.example"), [])
        self.assertEqual(self._user("biber@infinito.example")["enabled"], 0)

    def test_demotes_and_disables_a_member_an_earlier_run_provisioned(self) -> None:
        self._run({"manager": [_member("biber", "biber@infinito.example")]})

        output = self._run()

        self.assertEqual(
            output,
            [
                "CHANGED biber@infinito.example revoked Purchase User",
                "CHANGED biber@infinito.example revoked Sales User",
                "CHANGED biber@infinito.example disabled",
            ],
        )
        self.assertEqual(self._user("biber@infinito.example")["enabled"], 0)

    def test_keeps_a_directory_account_enabled_while_it_holds_an_unmanaged_role(
        self,
    ) -> None:
        self._seed_user(
            "dora@infinito.example",
            roles=("Sales User", "Security Check Approver"),
            links=(SSO,),
        )

        output = self._run()

        self.assertEqual(output, ["CHANGED dora@infinito.example revoked Sales User"])
        self.assertEqual(self._user("dora@infinito.example")["enabled"], 1)
        self.assertEqual(
            self._role_names("dora@infinito.example"), ["Security Check Approver"]
        )

    def test_strips_managed_roles_from_a_disabled_outsider_without_touching_its_state(
        self,
    ) -> None:
        self._seed_user(
            "biber@infinito.example", enabled=0, roles=("Customer",), links=(SSO,)
        )

        output = self._run()

        self.assertEqual(output, ["CHANGED biber@infinito.example revoked Customer"])
        self.assertEqual(self._user("biber@infinito.example")["enabled"], 0)

    def test_leaves_a_consumer_api_user_untouched(self) -> None:
        self._seed_user(
            API_USER, roles=("System Manager", "Accounts User", "Security Check Editor")
        )

        output = self._run()

        self.assertEqual(output, ["UNCHANGED"])
        self.assertEqual(self._user(API_USER)["enabled"], 1)
        self.assertEqual(
            self._role_names(API_USER),
            ["Accounts User", "Security Check Editor", "System Manager"],
        )

    def test_leaves_a_website_customer_untouched(self) -> None:
        self._seed_user("customer@shop.example", roles=("Customer",))

        output = self._run()

        self.assertEqual(output, ["UNCHANGED"])
        self.assertEqual(self._user("customer@shop.example")["enabled"], 1)
        self.assertEqual(self._role_names("customer@shop.example"), ["Customer"])

    def test_never_demotes_or_disables_a_protected_account(self) -> None:
        self._seed_user(PLATFORM_ADMIN, roles=("System Manager",), links=(SSO,))

        output = self._run()

        self.assertEqual(output, ["UNCHANGED"])
        for name in ("Administrator", "Guest", BOT, PLATFORM_ADMIN):
            self.assertEqual(self._user(name)["enabled"], 1)
        self.assertEqual(self._role_names(BOT), ["System Manager"])
        self.assertEqual(self._role_names(PLATFORM_ADMIN), ["System Manager"])

    def test_a_protected_member_gains_roles_but_keeps_its_other_managed_roles(
        self,
    ) -> None:
        self._seed_user(PLATFORM_ADMIN, roles=("System Manager",))

        output = self._run({"customer": [_member("platformadmin", PLATFORM_ADMIN)]})

        self.assertEqual(output, [f"CHANGED {PLATFORM_ADMIN} granted Customer"])
        self.assertEqual(
            self._role_names(PLATFORM_ADMIN), ["Customer", "System Manager"]
        )

    def test_a_second_run_changes_nothing(self) -> None:
        self._seed_user("biber@infinito.example")
        members = {"customer": [_member("carol", "carol@infinito.example")]}
        self._run(members)

        self.assertEqual(self._run(members), ["UNCHANGED"])

    def test_the_site_is_committed_and_released(self) -> None:
        self._run()

        self.assertTrue(self.frappe.db.committed)
        self.assertEqual(
            self.frappe.calls,
            [
                (
                    "init",
                    "next.erp.infinito.example",
                    "/home/frappe/frappe-bench/sites",
                ),
                ("connect",),
                ("destroy",),
            ],
        )

    def test_missing_protected_users_fails_before_touching_the_site(self) -> None:
        env = _env(NO_MEMBERS)
        del env["PROTECTED_USERS_JSON"]

        with self.assertRaises(KeyError):
            run_script(SCRIPT, self.frappe, env)

        self.assertEqual(self.frappe.calls, [])

    def test_missing_directory_provider_fails_before_touching_the_site(self) -> None:
        env = _env(NO_MEMBERS)
        del env["DIRECTORY_PROVIDER_NAME"]

        with self.assertRaises(KeyError):
            run_script(SCRIPT, self.frappe, env)

        self.assertEqual(self.frappe.calls, [])


if __name__ == "__main__":
    unittest.main()
