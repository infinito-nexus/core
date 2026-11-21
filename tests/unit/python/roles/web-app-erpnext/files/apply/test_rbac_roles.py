from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from . import PROJECT_ROOT
from ._fake_frappe import FakeFrappe, run_script

SCRIPT = PROJECT_ROOT / "roles/web-app-erpnext/files/python/apply/rbac_roles.py"
ADMINISTRATOR = "/roles/web-app-erpnext/administrator"
MANAGER = "/roles/web-app-erpnext/manager"
CUSTOMER = "/roles/web-app-erpnext/customer"
MAPPED_GROUP = "/roles/web-app-consumer/auditor"
MAPPED_ROLE = "Audit Editor"
GRANTS = {
    ADMINISTRATOR: ["System Manager"],
    MANAGER: ["Sales User", "Purchase User"],
    CUSTOMER: ["Customer"],
}
GROUP_ROLES = {MAPPED_GROUP: [MAPPED_ROLE]}
GRANT_PARENT = "infinito_rbac_mapped_role"
ID_PARENT = "infinito_rbac_directory_id"
CLAIMED = "infinito_rbac_claimed"
RECLAIM_PARENT = "infinito_rbac_directory_reclaim"
ALICE_UUID = "a11ce000-0000-4000-8000-000000000001"
NEWCOMER_UUID = "0e3c0000-0000-4000-8000-000000000002"
EVE_UUID = "0e7e0000-0000-4000-8000-000000000003"
SITE_ROLES = ("System Manager", "Sales User", "Purchase User", "Customer")
BOT = "erpnext-api-bot@infinito.example"
PLATFORM_ADMIN = "platformadmin@infinito.example"
PROTECTED = ["Administrator", "Guest", BOT, PLATFORM_ADMIN]
NO_MEMBERS = {ADMINISTRATOR: [], MANAGER: [], CUSTOMER: [], MAPPED_GROUP: []}
SSO = "keycloak"
DIRECTORY = "directory"
API_USER = "security-check-api@infinito.example"


def _env(members, ids=False):
    return {
        "SITE_NAME": "next.erp.infinito.example",
        "ROLE_GRANTS_JSON": json.dumps(GRANTS),
        "GROUP_ROLES_JSON": json.dumps(GROUP_ROLES),
        "ROLE_MEMBERS_JSON": json.dumps(members),
        "PROTECTED_USERS_JSON": json.dumps(PROTECTED),
        "PROTECTED_OWNERS_JSON": json.dumps({PLATFORM_ADMIN: "platformadmin"}),
        "SSO_PROVIDER_NAME": SSO,
        "DIRECTORY_PROVIDER_NAME": DIRECTORY,
        "DIRECTORY_IDS_JSON": json.dumps(ids),
        "DIRECTORY_UUID_ATTRIBUTE": "entryUUID",
    }


def _roles(*names):
    return [SimpleNamespace(role=name) for name in names]


def _links(name, *providers):
    userid = name.split("@")[0]
    return [
        SimpleNamespace(provider=provider, userid=userid, username=userid)
        for provider in providers
    ]


def _bound(*pairs):
    return [
        SimpleNamespace(provider=provider, userid=userid, username=userid)
        for provider, userid in pairs
    ]


def _member(username, email, uuid=""):
    return {"username": username, "email": email, "name": username, "uuid": uuid}


class TestRbacRoles(unittest.TestCase):
    def setUp(self) -> None:
        self.frappe = FakeFrappe()
        for role in SITE_ROLES:
            self.frappe.seed("Role", role, role_name=role)
        self.frappe.seed(
            "User", "Administrator", enabled=1, roles=_roles("System Manager")
        )
        self.frappe.seed("User", "Guest", enabled=1, roles=_roles("Guest"))
        self.frappe.seed(
            "User", BOT, email=BOT, enabled=1, roles=_roles("System Manager")
        )

    def _run(self, members=None, ids=None):
        members = {**NO_MEMBERS, **(members or {})}
        if ids is None:
            ids = any(
                member.get("uuid") for group in members.values() for member in group
            )
        printed = run_script(SCRIPT, self.frappe, _env(members, ids))
        return printed.splitlines()

    def _claimed(self):
        self.frappe.default_rows.append(
            {"parent": ID_PARENT, "defkey": CLAIMED, "defvalue": "1"}
        )

    def _user(self, name):
        return self.frappe.records["User"][name]

    def _role_names(self, name):
        return sorted(row.role for row in self._user(name)["roles"])

    def _link_rows(self, name):
        return [
            (row.provider, row.userid, row.username)
            for row in self._user(name)["social_logins"]
        ]

    def _record(self, name, role):
        self.frappe.default_rows.append(
            {"parent": GRANT_PARENT, "defkey": name, "defvalue": role}
        )

    def _grants(self, name):
        return self._values(GRANT_PARENT, name)

    def _record_id(self, name, uuid):
        self.frappe.default_rows.append(
            {"parent": ID_PARENT, "defkey": name, "defvalue": uuid}
        )
        if not self._ids(CLAIMED):
            self._claimed()

    def _ids(self, name):
        return self._values(ID_PARENT, name)

    def _values(self, parent, name):
        return {
            row["defvalue"]
            for row in self.frappe.default_rows
            if row["parent"] == parent and row["defkey"] == name
        }

    def _seed_user(self, name, enabled=1, roles=(), links=()):
        self.frappe.seed(
            "User",
            name,
            email=name,
            username=name.split("@")[0],
            enabled=enabled,
            roles=_roles(*roles),
            social_logins=_links(name, *links),
        )

    def test_creates_a_member_with_the_roles_of_its_group(self) -> None:
        output = self._run({MANAGER: [_member("alice", "Alice@infinito.example")]})

        self.assertEqual(
            output,
            [
                "CHANGED alice@infinito.example created",
                "CHANGED alice@infinito.example granted Purchase User",
                "CHANGED alice@infinito.example granted Sales User",
            ],
        )
        self.assertEqual(self._user("alice@infinito.example")["enabled"], 1)
        self.assertEqual(
            self._role_names("alice@infinito.example"), ["Purchase User", "Sales User"]
        )
        self.assertEqual(
            self._link_rows("alice@infinito.example"), [(DIRECTORY, "alice", "alice")]
        )

    def test_links_a_member_to_the_directory_under_its_username(self) -> None:
        self._seed_user("alice@infinito.example", roles=("Customer",))

        output = self._run({CUSTOMER: [_member("alice", "alice@infinito.example")]})

        self.assertEqual(output, ["CHANGED alice@infinito.example linked directory"])
        self.assertEqual(
            self._link_rows("alice@infinito.example"), [(DIRECTORY, "alice", "alice")]
        )

    def test_a_member_linked_by_its_keycloak_sign_in_gets_no_second_link(
        self,
    ) -> None:
        self._seed_user("alice@infinito.example", roles=("Customer",), links=(SSO,))

        output = self._run({CUSTOMER: [_member("alice", "alice@infinito.example")]})

        self.assertEqual(output, ["UNCHANGED"])
        self.assertEqual(
            self._link_rows("alice@infinito.example"), [(SSO, "alice", "alice")]
        )

    def test_reenables_a_disabled_member(self) -> None:
        self._seed_user("alice@infinito.example", enabled=0, links=(SSO,))

        output = self._run(
            {ADMINISTRATOR: [_member("alice", "alice@infinito.example")]}
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

        output = self._run({MANAGER: [_member("alice", "alice@infinito.example")]})

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
        self._run({MANAGER: [_member("biber", "biber@infinito.example")]})

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

        output = self._run({CUSTOMER: [_member("platformadmin", PLATFORM_ADMIN)]})

        self.assertEqual(output, [f"CHANGED {PLATFORM_ADMIN} granted Customer"])
        self.assertEqual(
            self._role_names(PLATFORM_ADMIN), ["Customer", "System Manager"]
        )

    def test_creates_a_mapped_role_the_site_lacks_before_granting_it(self) -> None:
        self._seed_bound("alice@infinito.example", (SSO, "alice"), roles=())

        output = self._run({MAPPED_GROUP: [_member("alice", "alice@infinito.example")]})

        self.assertEqual(
            output,
            [
                f"CHANGED created role {MAPPED_ROLE}",
                f"CHANGED alice@infinito.example granted {MAPPED_ROLE}",
            ],
        )
        self.assertIn(MAPPED_ROLE, self.frappe.records["Role"])
        self.assertEqual(self._role_names("alice@infinito.example"), [MAPPED_ROLE])
        self.assertEqual(self._grants("alice@infinito.example"), {MAPPED_ROLE})

    def test_a_mapped_group_never_takes_over_a_colliding_customer_account(
        self,
    ) -> None:
        self._seed_user("alice@infinito.example", enabled=0, roles=("Customer",))

        output = self._run({MAPPED_GROUP: [_member("alice", "alice@infinito.example")]})

        self.assertEqual(output, ["UNCHANGED"])
        user = self._user("alice@infinito.example")
        self.assertEqual((user["enabled"], user["social_logins"]), (0, []))
        self.assertEqual(self._role_names("alice@infinito.example"), ["Customer"])
        self.assertEqual(self.frappe.default_rows, [])
        self.assertNotIn(MAPPED_ROLE, self.frappe.records["Role"])

    def test_a_mapped_group_reaches_the_same_account_once_the_directory_owns_it(
        self,
    ) -> None:
        self._seed_bound("alice@infinito.example", (DIRECTORY, "alice"), enabled=0)

        output = self._run({MAPPED_GROUP: [_member("alice", "alice@infinito.example")]})

        self.assertEqual(
            output,
            [
                "CHANGED alice@infinito.example revoked Customer",
                "CHANGED alice@infinito.example enabled",
                f"CHANGED created role {MAPPED_ROLE}",
                f"CHANGED alice@infinito.example granted {MAPPED_ROLE}",
            ],
        )
        self.assertEqual(self._user("alice@infinito.example")["enabled"], 1)
        self.assertEqual(self._role_names("alice@infinito.example"), [MAPPED_ROLE])

    def test_revokes_a_mapped_role_from_a_member_who_left_its_group(self) -> None:
        self._seed_user(
            "alice@infinito.example",
            roles=(MAPPED_ROLE, "Sales User", "Purchase User", "Blogger"),
            links=(DIRECTORY,),
        )
        self._record("alice@infinito.example", MAPPED_ROLE)

        output = self._run({MANAGER: [_member("alice", "alice@infinito.example")]})

        self.assertEqual(
            output, [f"CHANGED alice@infinito.example revoked {MAPPED_ROLE}"]
        )
        self.assertEqual(
            self._role_names("alice@infinito.example"),
            ["Blogger", "Purchase User", "Sales User"],
        )
        self.assertEqual(self._grants("alice@infinito.example"), set())

    def test_revokes_a_mapped_role_outside_every_group_and_keeps_unmanaged_ones(
        self,
    ) -> None:
        self._seed_user(
            "alice@infinito.example", roles=(MAPPED_ROLE, "Blogger"), links=(SSO,)
        )
        self._record("alice@infinito.example", MAPPED_ROLE)

        output = self._run()

        self.assertEqual(
            output, [f"CHANGED alice@infinito.example revoked {MAPPED_ROLE}"]
        )
        self.assertEqual(self._role_names("alice@infinito.example"), ["Blogger"])
        self.assertEqual(self._user("alice@infinito.example")["enabled"], 1)

    def test_revokes_and_disables_when_the_recorded_mapped_role_was_the_last_role(
        self,
    ) -> None:
        self._seed_user("alice@infinito.example", roles=(MAPPED_ROLE,), links=(SSO,))
        self._record("alice@infinito.example", MAPPED_ROLE)

        output = self._run()

        self.assertEqual(
            output,
            [
                f"CHANGED alice@infinito.example revoked {MAPPED_ROLE}",
                "CHANGED alice@infinito.example disabled",
            ],
        )
        self.assertEqual(self._user("alice@infinito.example")["enabled"], 0)

    def test_a_mapped_role_granted_by_hand_outlives_the_membership(self) -> None:
        self.frappe.seed("Role", MAPPED_ROLE, role_name=MAPPED_ROLE)
        self._seed_bound("alice@infinito.example", (SSO, "alice"), roles=(MAPPED_ROLE,))
        member = {MAPPED_GROUP: [_member("alice", "alice@infinito.example")]}

        self.assertEqual(self._run(member), ["UNCHANGED"])
        self.assertEqual(self._grants("alice@infinito.example"), set())
        self.assertEqual(self._run(), ["UNCHANGED"])
        self.assertEqual(self._role_names("alice@infinito.example"), [MAPPED_ROLE])
        self.assertEqual(self._user("alice@infinito.example")["enabled"], 1)

    def test_a_renamed_account_carries_the_record_of_its_mapped_grants(self) -> None:
        self._seed_bound(
            "alice@infinito.example",
            (DIRECTORY, "alice"),
            roles=("Customer", MAPPED_ROLE),
            uuid=ALICE_UUID,
        )
        self._record("alice@infinito.example", MAPPED_ROLE)

        output = self._run(
            {CUSTOMER: [_member("alice", "alice.new@infinito.example", ALICE_UUID)]}
        )

        self.assertEqual(
            output,
            [
                "CHANGED alice@infinito.example renamed to alice.new@infinito.example",
                f"CHANGED alice.new@infinito.example revoked {MAPPED_ROLE}",
            ],
        )
        self.assertEqual(
            [row for row in self.frappe.default_rows if row["defkey"] != CLAIMED],
            [
                {
                    "parent": ID_PARENT,
                    "defkey": "alice.new@infinito.example",
                    "defvalue": ALICE_UUID,
                }
            ],
        )
        self.assertEqual(self._role_names("alice.new@infinito.example"), ["Customer"])

    def test_a_mapped_role_never_touches_an_account_the_directory_does_not_own(
        self,
    ) -> None:
        self.frappe.seed("Role", MAPPED_ROLE, role_name=MAPPED_ROLE)
        self._seed_user(API_USER, roles=(MAPPED_ROLE,))

        output = self._run({MAPPED_GROUP: [_member("alice", "alice@infinito.example")]})

        self.assertNotIn(API_USER, " ".join(output))
        self.assertEqual(self._role_names(API_USER), [MAPPED_ROLE])
        self.assertEqual(self._user(API_USER)["enabled"], 1)

    def _seed_bound(self, name, *pairs, roles=("Customer",), enabled=1, uuid=""):
        self.frappe.seed(
            "User",
            name,
            email=name,
            enabled=enabled,
            roles=_roles(*roles),
            social_logins=_bound(*pairs),
        )
        if uuid:
            self._record_id(name, uuid)

    def _renames(self):
        return [call[1:4] for call in self.frappe.calls if call[0] == "rename_doc"]

    def test_renames_the_directory_account_of_a_member_whose_address_changed(
        self,
    ) -> None:
        self._seed_bound(
            "alice@infinito.example", (DIRECTORY, "alice"), uuid=ALICE_UUID
        )

        output = self._run(
            {CUSTOMER: [_member("alice", "alice.new@infinito.example", ALICE_UUID)]}
        )

        self.assertEqual(
            output,
            ["CHANGED alice@infinito.example renamed to alice.new@infinito.example"],
        )
        self.assertNotIn("alice@infinito.example", self.frappe.records["User"])
        user = self._user("alice.new@infinito.example")
        self.assertEqual((user["email"], user["enabled"]), (user["name"], 1))
        self.assertEqual(self._role_names("alice.new@infinito.example"), ["Customer"])
        self.assertEqual(
            self._link_rows("alice.new@infinito.example"),
            [(DIRECTORY, "alice", "alice")],
        )

    def test_renames_an_account_its_keycloak_sign_in_bound_to_the_member(
        self,
    ) -> None:
        self._seed_bound("alice@infinito.example", (SSO, "alice"), uuid=ALICE_UUID)

        self._run(
            {CUSTOMER: [_member("alice", "alice.new@infinito.example", ALICE_UUID)]}
        )

        self.assertEqual(
            self._renames(),
            [("User", "alice@infinito.example", "alice.new@infinito.example")],
        )

    def test_the_rename_flashes_nothing_to_a_session(self) -> None:
        self._seed_bound(
            "alice@infinito.example", (DIRECTORY, "alice"), uuid=ALICE_UUID
        )

        self._run(
            {CUSTOMER: [_member("alice", "alice.new@infinito.example", ALICE_UUID)]}
        )

        self.assertEqual(
            [call[4] for call in self.frappe.calls if call[0] == "rename_doc"],
            [False],
        )

    def test_a_renamed_member_is_unchanged_on_the_next_run(self) -> None:
        self._seed_bound(
            "alice@infinito.example", (DIRECTORY, "alice"), uuid=ALICE_UUID
        )
        members = {
            CUSTOMER: [_member("alice", "alice.new@infinito.example", ALICE_UUID)]
        }
        self._run(members)

        self.assertEqual(self._run(members), ["UNCHANGED"])

    def test_renames_the_account_of_a_mapped_member_whose_address_changed(
        self,
    ) -> None:
        self._seed_bound(
            "alice@infinito.example",
            (DIRECTORY, "alice"),
            roles=(MAPPED_ROLE,),
            uuid=ALICE_UUID,
        )
        self._record("alice@infinito.example", MAPPED_ROLE)
        members = {
            MAPPED_GROUP: [_member("alice", "alice.new@infinito.example", ALICE_UUID)]
        }

        output = self._run(members)

        self.assertEqual(
            output,
            ["CHANGED alice@infinito.example renamed to alice.new@infinito.example"],
        )
        self.assertEqual(self._role_names("alice.new@infinito.example"), [MAPPED_ROLE])
        self.assertEqual(self._grants("alice.new@infinito.example"), {MAPPED_ROLE})
        self.assertEqual(self._run(members), ["UNCHANGED"])

    def test_a_mapped_member_bound_to_no_account_gets_none(self) -> None:
        self._seed_bound(
            "alice@infinito.example", (DIRECTORY, "alice"), roles=(MAPPED_ROLE,)
        )
        self._record("alice@infinito.example", MAPPED_ROLE)

        output = self._run(
            {MAPPED_GROUP: [_member("mallory", "mallory@infinito.example")]}
        )

        self.assertEqual(self._renames(), [])
        self.assertNotIn("mallory@infinito.example", self.frappe.records["User"])
        self.assertEqual(
            output,
            [
                f"CHANGED alice@infinito.example revoked {MAPPED_ROLE}",
                "CHANGED alice@infinito.example disabled",
            ],
        )

    def test_a_row_of_another_provider_binds_no_account(self) -> None:
        self._seed_bound("alice@infinito.example", ("google", "alice"))

        output = self._run({CUSTOMER: [_member("alice", "alice.new@infinito.example")]})

        self.assertEqual(self._renames(), [])
        self.assertIn("CHANGED alice.new@infinito.example created", output)

    def test_an_account_bound_to_another_username_is_not_renamed(self) -> None:
        self._seed_bound("alice@infinito.example", (DIRECTORY, "alice"))

        self._run({CUSTOMER: [_member("mallory", "mallory@infinito.example")]})

        self.assertEqual(self._renames(), [])
        self.assertIn("alice@infinito.example", self.frappe.records["User"])

    def test_an_account_another_member_holds_by_address_is_not_renamed(
        self,
    ) -> None:
        self._seed_bound(
            "alice@infinito.example", (DIRECTORY, "alice"), uuid=ALICE_UUID
        )

        self._run(
            {
                CUSTOMER: [
                    _member("alice", "alice.new@infinito.example", ALICE_UUID),
                    _member("bob", "alice@infinito.example"),
                ]
            }
        )

        self.assertEqual(self._renames(), [])
        self.assertIn("alice@infinito.example", self.frappe.records["User"])

    def test_a_member_bound_to_two_accounts_gets_neither_renamed(self) -> None:
        self._seed_bound(
            "alice@infinito.example", (DIRECTORY, "alice"), uuid=ALICE_UUID
        )
        self._seed_bound("alice.old@infinito.example", (SSO, "alice"), uuid=ALICE_UUID)

        self._run(
            {CUSTOMER: [_member("alice", "alice.new@infinito.example", ALICE_UUID)]}
        )

        self.assertEqual(self._renames(), [])

    def test_a_protected_account_is_never_renamed(self) -> None:
        self._seed_bound(
            PLATFORM_ADMIN, (SSO, "platformadmin"), roles=(), uuid=ALICE_UUID
        )

        self._run(
            {
                ADMINISTRATOR: [
                    _member("platformadmin", "root@infinito.example", ALICE_UUID)
                ]
            }
        )

        self.assertEqual(self._renames(), [])
        self.assertIn(PLATFORM_ADMIN, self.frappe.records["User"])

    def test_an_account_without_a_recorded_directory_id_is_never_adopted(self) -> None:
        for group in (CUSTOMER, MAPPED_GROUP):
            with self.subTest(group=group):
                self.setUp()
                self._seed_bound(
                    "alice@infinito.example", (DIRECTORY, "alice"), roles=("Blogger",)
                )

                output = self._run(
                    {
                        group: [
                            _member("alice", "alice.new@infinito.example", ALICE_UUID)
                        ]
                    }
                )

                self.assertEqual(self._renames(), [])
                self.assertIn("CHANGED alice.new@infinito.example created", output)
                old = self._user("alice@infinito.example")
                self.assertEqual(
                    (old["enabled"], self._role_names(old["name"])), (1, ["Blogger"])
                )
                self.assertEqual(self._ids("alice@infinito.example"), set())
                self.assertEqual(self._ids("alice.new@infinito.example"), {ALICE_UUID})
                self.assertEqual(
                    self._link_rows("alice.new@infinito.example"),
                    [(DIRECTORY, "alice", "alice")],
                )

    def test_a_reused_username_never_inherits_the_former_account(self) -> None:
        paths = {
            "an unmanaged role keeps the departed account enabled": (
                ("Security Check Approver",),
                (1, ["Security Check Approver"]),
            ),
            "departure and reuse fall into one sync run": (
                ("Customer",),
                (0, []),
            ),
        }
        for group in (CUSTOMER, MAPPED_GROUP):
            for path, (roles, after) in paths.items():
                with self.subTest(group=group, path=path):
                    self.setUp()
                    self._seed_bound(
                        "alice@infinito.example",
                        (DIRECTORY, "alice"),
                        roles=roles,
                        uuid=ALICE_UUID,
                    )

                    output = self._run(
                        {
                            group: [
                                _member(
                                    "alice", "newcomer@infinito.example", NEWCOMER_UUID
                                )
                            ]
                        }
                    )

                    self.assertEqual(self._renames(), [])
                    self.assertIn("CHANGED newcomer@infinito.example created", output)
                    old = self._user("alice@infinito.example")
                    self.assertEqual(
                        (old["enabled"], self._role_names(old["name"])), after
                    )
                    self.assertEqual(self._ids("alice@infinito.example"), {ALICE_UUID})
                    self.assertEqual(
                        self._ids("newcomer@infinito.example"), {NEWCOMER_UUID}
                    )

    def test_the_same_directory_entry_takes_its_account_along(self) -> None:
        for group in (CUSTOMER, MAPPED_GROUP):
            with self.subTest(group=group):
                self.setUp()
                self._seed_bound(
                    "alice@infinito.example",
                    (DIRECTORY, "alice"),
                    roles=("Security Check Approver",),
                    uuid=ALICE_UUID,
                )

                self._run(
                    {
                        group: [
                            _member("alice", "alice.new@infinito.example", ALICE_UUID)
                        ]
                    }
                )

                self.assertEqual(
                    self._renames(),
                    [("User", "alice@infinito.example", "alice.new@infinito.example")],
                )
                self.assertIn(
                    "Security Check Approver",
                    self._role_names("alice.new@infinito.example"),
                )

    def test_records_the_directory_id_of_a_member_on_its_account(self) -> None:
        self._seed_user("bob@infinito.example", roles=("Customer",), links=(SSO,))
        members = {
            CUSTOMER: [
                _member("alice", "alice@infinito.example", ALICE_UUID),
                _member("bob", "bob@infinito.example", NEWCOMER_UUID),
            ]
        }

        output = self._run(members)

        self.assertIn(
            "CHANGED alice@infinito.example recorded its directory id", output
        )
        self.assertIn("CHANGED bob@infinito.example recorded its directory id", output)
        self.assertEqual(self._ids("alice@infinito.example"), {ALICE_UUID})
        self.assertEqual(self._ids("bob@infinito.example"), {NEWCOMER_UUID})
        self.assertEqual(self._run(members), ["UNCHANGED"])

    def test_core_roles_never_land_on_an_account_bound_to_another_member(
        self,
    ) -> None:
        accounts = {
            "a row names another userid": ((DIRECTORY, "alice"), ""),
            "another directory id is recorded": ((DIRECTORY, "bob"), ALICE_UUID),
        }
        for group, role in ((CUSTOMER, "Customer"), (ADMINISTRATOR, "System Manager")):
            for case, (pair, uuid) in accounts.items():
                with self.subTest(group=group, role=role, case=case):
                    self.setUp()
                    self._seed_bound(
                        "alice@infinito.example", pair, roles=(), enabled=0, uuid=uuid
                    )

                    self._run(
                        {
                            group: [
                                _member("bob", "alice@infinito.example", NEWCOMER_UUID)
                            ]
                        }
                    )

                    user = self._user("alice@infinito.example")
                    self.assertEqual(
                        (user["enabled"], self._role_names(user["name"])), (0, [])
                    )
                    self.assertNotIn(NEWCOMER_UUID, self._ids("alice@infinito.example"))

    def test_a_reused_username_at_the_same_address_never_reopens_the_account(
        self,
    ) -> None:
        accounts = {
            "another directory id is recorded": (
                ALICE_UUID,
                "its recorded directory id is not the member's",
            ),
            "no directory id is recorded": (
                "",
                "it is disabled and carries no directory id",
            ),
        }
        for group in (CUSTOMER, MAPPED_GROUP):
            for case, (recorded, reason) in accounts.items():
                with self.subTest(group=group, case=case):
                    self.setUp()
                    self._seed_bound(
                        "alice@infinito.example",
                        (DIRECTORY, "alice"),
                        roles=(),
                        enabled=0,
                        uuid=recorded,
                    )

                    output = self._run(
                        {
                            group: [
                                _member(
                                    "alice", "alice@infinito.example", NEWCOMER_UUID
                                )
                            ]
                        }
                    )

                    self.assertIn(f"REFUSED alice@infinito.example {reason}", output)
                    user = self._user("alice@infinito.example")
                    self.assertEqual(
                        (user["enabled"], self._role_names(user["name"])), (0, [])
                    )
                    self.assertEqual(
                        self._ids("alice@infinito.example"),
                        {recorded} - {""},
                    )

    def test_the_recorded_directory_entry_reopens_its_disabled_account(self) -> None:
        for group, role in ((CUSTOMER, "Customer"), (MAPPED_GROUP, MAPPED_ROLE)):
            with self.subTest(group=group):
                self.setUp()
                self._seed_bound(
                    "alice@infinito.example",
                    (DIRECTORY, "alice"),
                    roles=(),
                    enabled=0,
                    uuid=ALICE_UUID,
                )

                output = self._run(
                    {group: [_member("alice", "alice@infinito.example", ALICE_UUID)]}
                )

                self.assertIn("CHANGED alice@infinito.example enabled", output)
                self.assertFalse([line for line in output if "REFUSED" in line])
                user = self._user("alice@infinito.example")
                self.assertEqual(
                    (user["enabled"], self._role_names(user["name"])), (1, [role])
                )

    def test_without_directory_ids_the_run_neither_records_nor_checks_one(
        self,
    ) -> None:
        members = {
            CUSTOMER: [
                _member("alice", "alice@infinito.example", ALICE_UUID),
                _member("bob", "bob@infinito.example", NEWCOMER_UUID),
            ]
        }
        for ids in (False, True):
            with self.subTest(ids=ids):
                self.setUp()
                self._seed_bound(
                    "alice@infinito.example",
                    (DIRECTORY, "alice"),
                    roles=(),
                    enabled=0,
                    uuid=NEWCOMER_UUID,
                )
                self._seed_bound("bob@infinito.example", (DIRECTORY, "bob"), roles=())

                output = self._run(members, ids=ids)

                refused = [line for line in output if line.startswith("REFUSED")]
                alice = self._user("alice@infinito.example")
                if ids:
                    self.assertEqual(
                        refused,
                        [
                            (
                                "REFUSED alice@infinito.example its recorded "
                                "directory id is not the member's"
                            ),
                            "REFUSED bob@infinito.example it carries no directory id",
                        ],
                    )
                    self.assertEqual(alice["enabled"], 0)
                else:
                    self.assertEqual(refused, [])
                    self.assertEqual(
                        (alice["enabled"], self._role_names(alice["name"])),
                        (1, ["Customer"]),
                    )
                    self.assertEqual(self._ids("bob@infinito.example"), set())

    def test_after_the_first_run_an_account_without_a_directory_id_is_never_claimed(
        self,
    ) -> None:
        for group in (CUSTOMER, MAPPED_GROUP):
            with self.subTest(group=group):
                self.setUp()
                self._claimed()
                self._seed_bound(
                    "alice@infinito.example",
                    (DIRECTORY, "alice"),
                    roles=("Security Check Approver",),
                )

                output = self._run(
                    {group: [_member("alice", "alice@infinito.example", NEWCOMER_UUID)]}
                )

                self.assertIn(
                    "REFUSED alice@infinito.example it carries no directory id", output
                )
                self.assertEqual(self._ids("alice@infinito.example"), set())
                self.assertEqual(
                    self._role_names("alice@infinito.example"),
                    ["Security Check Approver"],
                )

    def test_the_first_run_claims_the_accounts_of_the_current_members_once(
        self,
    ) -> None:
        for group in (CUSTOMER, MAPPED_GROUP):
            with self.subTest(group=group):
                self.setUp()
                self._seed_bound(
                    "alice@infinito.example",
                    (DIRECTORY, "alice"),
                    roles=("Security Check Approver",),
                )
                members = {
                    group: [_member("alice", "alice@infinito.example", ALICE_UUID)]
                }

                first = self._run(members)
                second = self._run(members)

                self.assertIn(
                    "CHANGED alice@infinito.example recorded its directory id", first
                )
                self.assertIn("CHANGED directory ids claimed", first)
                self.assertEqual(self._ids("alice@infinito.example"), {ALICE_UUID})
                self.assertEqual(self._ids(CLAIMED), {"1"})
                self.assertFalse([line for line in second if "claimed" in line])

    def test_a_renamed_directory_user_keeps_its_account(self) -> None:
        for group, role in ((CUSTOMER, "Customer"), (MAPPED_GROUP, MAPPED_ROLE)):
            for email in ("alice@infinito.example", "alice.new@infinito.example"):
                with self.subTest(group=group, email=email):
                    self.setUp()
                    self._seed_bound(
                        "alice@infinito.example",
                        (DIRECTORY, "alice"),
                        roles=(),
                        uuid=ALICE_UUID,
                    )

                    output = self._run({group: [_member("alice2", email, ALICE_UUID)]})

                    self.assertFalse([line for line in output if "REFUSED" in line])
                    self.assertNotIn(f"CHANGED {email} created", output)
                    self.assertIn(f"CHANGED {email} rebound to alice2", output)
                    self.assertEqual(
                        self._link_rows(email), [(DIRECTORY, "alice2", "alice2")]
                    )
                    self.assertEqual(self._role_names(email), [role])
                    self.assertEqual(self._ids(email), {ALICE_UUID})

    def test_a_protected_member_is_never_refused_for_a_missing_directory_id(
        self,
    ) -> None:
        alice = "alice@infinito.example"
        self._claimed()
        self.frappe.seed(
            "User",
            PLATFORM_ADMIN,
            email=PLATFORM_ADMIN,
            enabled=1,
            roles=_roles("System Manager"),
            social_logins=_bound((SSO, "platformadmin")),
        )
        self._seed_bound(alice, (SSO, "alice"), roles=())

        output = self._run(
            {
                ADMINISTRATOR: [
                    _member("platformadmin", PLATFORM_ADMIN, NEWCOMER_UUID)
                ],
                CUSTOMER: [_member("alice", alice, ALICE_UUID)],
            }
        )

        self.assertEqual(
            [line for line in output if line.startswith("REFUSED")],
            [f"REFUSED {alice} it carries no directory id"],
        )
        self.assertEqual(self._role_names(PLATFORM_ADMIN), ["System Manager"])
        self.assertEqual(self._user(PLATFORM_ADMIN)["enabled"], 1)
        self.assertEqual(self._ids(PLATFORM_ADMIN), set())
        self.assertEqual(self._role_names(alice), [])

    def test_a_reclaim_records_the_id_anew_only_for_a_single_directory_entry(
        self,
    ) -> None:
        alice = "alice@infinito.example"
        single = [{"uid": "alice", "mail": alice, "entryUUID": ALICE_UUID}]
        reclaimed = f"CHANGED {alice} reclaimed its directory id"
        dropped = f"REFUSED {alice} its reclaim request is dropped: "
        twice = (
            f"{dropped}the directory entries with its username or address "
            "are not the member's alone"
        )
        cases = {
            "a stale id, one entry": (True, NEWCOMER_UUID, single, reclaimed),
            "no id, one entry": (True, "", single, reclaimed),
            "the address held twice": (
                True,
                NEWCOMER_UUID,
                [*single, {"uid": "alice.old", "mail": alice, "entryUUID": "x"}],
                twice,
            ),
            "the username held twice": (
                True,
                NEWCOMER_UUID,
                [*single, {"uid": "alice", "mail": "old@x.example", "entryUUID": "x"}],
                twice,
            ),
            "the directory down": (
                True,
                NEWCOMER_UUID,
                None,
                f"{dropped}the directory could not be searched: OSError",
            ),
            "no request": (
                False,
                NEWCOMER_UUID,
                single,
                f"REFUSED {alice} its recorded directory id is not the member's",
            ),
        }
        for group, role in ((CUSTOMER, "Customer"), (MAPPED_GROUP, MAPPED_ROLE)):
            for case, (requested, recorded, directory, line) in cases.items():
                with self.subTest(group=group, case=case):
                    self.setUp()
                    self._claimed()
                    self._seed_bound(
                        alice, (DIRECTORY, "alice"), roles=(), uuid=recorded
                    )
                    if requested:
                        self.frappe.default_rows.append(
                            {"parent": RECLAIM_PARENT, "defkey": alice, "defvalue": "1"}
                        )
                    self.frappe.directory = directory or []
                    self.frappe.outage = directory is None

                    output = self._run({group: [_member("alice", alice, ALICE_UUID)]})

                    self.assertIn(line, output)
                    done = line == reclaimed
                    self.assertEqual(
                        self._ids(alice),
                        {ALICE_UUID} if done else ({recorded} - {""}),
                    )
                    self.assertEqual(self._values(RECLAIM_PARENT, alice), set())
                    self.assertEqual(self._role_names(alice), [role] if done else [])
                    self.assertEqual(self.frappe.unbinds, int(requested))

    def test_a_reclaim_request_never_outlives_the_run_after_it(self) -> None:
        alice = "alice@infinito.example"
        for member in (False, True):
            with self.subTest(member=member):
                self.setUp()
                self._claimed()
                self._seed_bound(alice, (DIRECTORY, "alice"), uuid=ALICE_UUID)
                self.frappe.default_rows.append(
                    {"parent": RECLAIM_PARENT, "defkey": alice, "defvalue": "1"}
                )
                self.frappe.directory = [
                    {"uid": "alice", "mail": alice, "entryUUID": NEWCOMER_UUID}
                ]
                newcomer = {CUSTOMER: [_member("alice", alice, NEWCOMER_UUID)]}

                first = self._run(newcomer if member else {}, ids=True)
                second = self._run(newcomer)

                self.assertEqual(
                    f"CHANGED {alice} reclaimed its directory id" in first, member
                )
                if not member:
                    self.assertIn(
                        f"REFUSED {alice} its reclaim request is dropped: no member's "
                        "account the run converged is at its address",
                        first,
                    )
                    self.assertIn(
                        f"REFUSED {alice} its recorded directory id is not the member's",
                        second,
                    )
                self.assertEqual(self._values(RECLAIM_PARENT, alice), set())
                self.assertEqual(
                    self._ids(alice), {NEWCOMER_UUID if member else ALICE_UUID}
                )
                self.assertEqual(self._user(alice)["enabled"], int(member))

    def test_the_marker_waits_for_a_run_with_a_directory_id(self) -> None:
        for uuid in ("", ALICE_UUID):
            with self.subTest(uuid=uuid):
                self.setUp()

                output = self._run(
                    {CUSTOMER: [_member("alice", "alice@infinito.example", uuid)]},
                    ids=True,
                )

                self.assertEqual("CHANGED directory ids claimed" in output, bool(uuid))
                self.assertEqual(self._ids(CLAIMED), {"1"} if uuid else set())

    def test_the_owned_loop_rebinds_only_an_identified_account(self) -> None:
        alice = "alice@infinito.example"
        for ids in (False, True):
            with self.subTest(ids=ids):
                self.setUp()
                self._seed_bound(
                    alice,
                    (SSO, "alice"),
                    (DIRECTORY, "mallory"),
                    roles=(),
                    uuid=ALICE_UUID if ids else "",
                )

                output = self._run(
                    {MAPPED_GROUP: [_member("alice", alice, ALICE_UUID)]}, ids=ids
                )

                bound = "alice" if ids else "mallory"
                self.assertEqual(
                    f"CHANGED {alice} rebound to alice" in output, ids, output
                )
                self.assertEqual(
                    self._link_rows(alice),
                    [(SSO, "alice", "alice"), (DIRECTORY, bound, bound)],
                )
                self.assertEqual(self._role_names(alice), [MAPPED_ROLE])

    def test_an_address_two_directory_entries_hold_is_refused(self) -> None:
        shared = "shared@infinito.example"
        alice = _member("alice", shared, ALICE_UUID)
        for auditor in (_member("mallory", shared, NEWCOMER_UUID), alice):
            with self.subTest(auditor=auditor["username"]):
                self.setUp()

                output = self._run({CUSTOMER: [alice], MAPPED_GROUP: [auditor]})

                ambiguous = auditor is not alice
                self.assertEqual(
                    f"REFUSED {shared} more than one directory entry holds its address"
                    in output,
                    ambiguous,
                )
                if ambiguous:
                    self.assertNotIn(shared, self.frappe.records["User"])
                else:
                    self.assertEqual(
                        self._role_names(shared), sorted(["Customer", MAPPED_ROLE])
                    )

    def test_a_padded_member_address_is_the_same_address(self) -> None:
        shared = "shared@infinito.example"

        output = self._run(
            {
                CUSTOMER: [_member("alice", f"{shared.upper()} ", ALICE_UUID)],
                MAPPED_GROUP: [_member("mallory", shared, NEWCOMER_UUID)],
            }
        )

        self.assertIn(
            f"REFUSED {shared} more than one directory entry holds its address", output
        )
        self.assertNotIn(shared, self.frappe.records["User"])

    def test_the_sync_never_claims_a_protected_account_for_another_member(
        self,
    ) -> None:
        refused = f"REFUSED {PLATFORM_ADMIN} the account is protected and not the member's own"
        for exists, group in (
            (True, CUSTOMER),
            (False, ADMINISTRATOR),
            (False, MAPPED_GROUP),
        ):
            for username in ("eve", "platformadmin"):
                with self.subTest(exists=exists, group=group, username=username):
                    self.setUp()
                    if exists:
                        self._seed_user(PLATFORM_ADMIN, roles=("System Manager",))
                    member = _member(username, PLATFORM_ADMIN, EVE_UUID)

                    output = self._run({group: [member]}, ids=True)

                    owner = username == "platformadmin"
                    self.assertEqual(refused in output, not owner, output)
                    created = owner and group != MAPPED_GROUP
                    self.assertEqual(
                        PLATFORM_ADMIN in self.frappe.records["User"], exists or created
                    )
                    if exists:
                        self.assertEqual(self._link_rows(PLATFORM_ADMIN), [])
                        self.assertEqual(
                            "Customer" in self._role_names(PLATFORM_ADMIN), owner
                        )

    def test_a_rowless_protected_account_outside_the_owners_is_refused(self) -> None:
        self.frappe.records["User"][BOT]["username"] = "erpnext-api-bot"

        output = self._run({CUSTOMER: [_member("erpnext-api-bot", BOT, EVE_UUID)]})

        self.assertIn(
            f"REFUSED {BOT} the account is protected and not the member's own", output
        )
        self.assertEqual(self._role_names(BOT), ["System Manager"])

    def test_a_new_protected_account_carries_no_directory_id(self) -> None:
        former = "pa.old@infinito.example"
        for group, recorded in (
            (ADMINISTRATOR, ""),
            (ADMINISTRATOR, NEWCOMER_UUID),
            (MAPPED_GROUP, NEWCOMER_UUID),
        ):
            with self.subTest(group=group, recorded=recorded):
                self.setUp()
                self._seed_bound(former, (SSO, "platformadmin"), uuid=recorded)
                admin = _member("platformadmin", PLATFORM_ADMIN, NEWCOMER_UUID)

                output = self._run({group: [admin]}, ids=True)

                self.assertIn(f"CHANGED {PLATFORM_ADMIN} created", output)
                self.assertEqual(self._ids(PLATFORM_ADMIN), set())
                self.assertIn(former, self.frappe.records["User"])

    def test_a_reclaim_request_on_a_protected_account_is_dropped_as_protected(
        self,
    ) -> None:
        for member in (True, False):
            with self.subTest(member=member):
                self.setUp()
                self._claimed()
                self.frappe.seed(
                    "User",
                    PLATFORM_ADMIN,
                    email=PLATFORM_ADMIN,
                    enabled=1,
                    roles=_roles("System Manager"),
                    social_logins=_bound((SSO, "platformadmin")),
                )
                self.frappe.default_rows.append(
                    {
                        "parent": RECLAIM_PARENT,
                        "defkey": PLATFORM_ADMIN,
                        "defvalue": "1",
                    }
                )
                self.frappe.directory = [
                    {
                        "uid": "platformadmin",
                        "mail": PLATFORM_ADMIN,
                        "entryUUID": NEWCOMER_UUID,
                    }
                ]
                admin = _member("platformadmin", PLATFORM_ADMIN, NEWCOMER_UUID)

                output = self._run({ADMINISTRATOR: [admin] if member else []}, ids=True)

                self.assertIn(
                    f"REFUSED {PLATFORM_ADMIN} its reclaim request is dropped: "
                    "the account is protected",
                    output,
                )
                self.assertEqual(self._values(RECLAIM_PARENT, PLATFORM_ADMIN), set())
                self.assertEqual(self._ids(PLATFORM_ADMIN), set())
                self.assertEqual(self._role_names(PLATFORM_ADMIN), ["System Manager"])
                self.assertEqual(self.frappe.unbinds, 0)

    def test_a_mapped_member_whose_adoption_is_impossible_gets_a_new_account(
        self,
    ) -> None:
        cases = {
            "two bound accounts": (
                [
                    ("alice@infinito.example", (DIRECTORY, "alice")),
                    ("alice.old@infinito.example", (SSO, "alice")),
                ],
                {},
            ),
            "former account held by another member": (
                [("alice@infinito.example", (DIRECTORY, "alice"))],
                {CUSTOMER: [_member("bob", "alice@infinito.example")]},
            ),
            "protected former account": (
                [(PLATFORM_ADMIN, (SSO, "alice"))],
                {},
            ),
        }
        for case, (accounts, others) in cases.items():
            with self.subTest(case=case):
                self.setUp()
                for name, pair in accounts:
                    self._seed_bound(name, pair, roles=(), uuid=ALICE_UUID)

                output = self._run(
                    {
                        **others,
                        MAPPED_GROUP: [
                            _member("alice", "alice.new@infinito.example", ALICE_UUID)
                        ],
                    }
                )

                self.assertEqual(self._renames(), [])
                self.assertIn("CHANGED alice.new@infinito.example created", output)
                self.assertEqual(
                    self._role_names("alice.new@infinito.example"), [MAPPED_ROLE]
                )
                for name, _ in accounts:
                    self.assertIn(name, self.frappe.records["User"])

    def test_a_mapped_role_never_lands_on_an_account_bound_to_another_member(
        self,
    ) -> None:
        self._seed_bound("alice@infinito.example", (DIRECTORY, "alice"), roles=())

        output = self._run({MAPPED_GROUP: [_member("bob", "alice@infinito.example")]})

        self.assertEqual(self._role_names("alice@infinito.example"), [])
        self.assertEqual(self._grants("alice@infinito.example"), set())
        self.assertEqual(
            output,
            [
                "REFUSED alice@infinito.example a row binds it to another directory user",
                "CHANGED alice@infinito.example disabled",
            ],
        )

    def test_a_second_run_changes_nothing(self) -> None:
        self._seed_user("biber@infinito.example")
        members = {CUSTOMER: [_member("carol", "carol@infinito.example")]}
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
