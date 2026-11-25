import importlib.util
import unittest
from pathlib import Path

from ansible.errors import AnsibleFilterError

PLUGIN = (
    Path(__file__).parent
    / "../../../../../roles/svc-db-openldap/filter_plugins/ldap_user_entries.py"
).resolve()


def _load():
    spec = importlib.util.spec_from_file_location("ldap_user_entries", str(PLUGIN))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


USERS = {
    "alice": {
        "username": "alice",
        "firstname": "Alice",
        "lastname": "Liddell",
        "uid": "1001",
        "gid": 1001,
        "email": "alice@example.org",
    },
    "bob": {
        "username": "bob",
        "firstname": "Bob",
        "lastname": "Builder",
        "cn": "Bob B.",
        "uid": 1002,
        "gid": 1002,
        "email": "bob@example.org",
    },
}
STRUCTURAL = ["person", "inetOrgPerson", "posixAccount"]
RENAME_USERS = {
    "platform_administrator": {"username": "platformadmin"},
    "biber": {"username": "biber"},
}
OLD_DN = "uid=platform_administrator,ou=users,dc=x"
NEW_DN = "uid=platformadmin,ou=users,dc=x"
BIBER_DN = "uid=biber,ou=users,dc=x"
ADMIN_GROUP = "cn=app-administrator,ou=roles,dc=x"
POSIX_GROUP = "cn=app-posix,ou=roles,dc=x"
EDITOR_GROUP = "cn=app-editor,ou=roles,dc=x"
USERS_DN = "ou=users,dc=x"


def _made_here(dn, uids, home):
    return {
        "dn": dn,
        "uid": uids,
        "objectClass": ["top", *STRUCTURAL],
        "homeDirectory": home,
    }


LEGACY_ENTRIES = [
    _made_here(
        OLD_DN,
        ["platformadmin", "platform_administrator"],
        "/home/platform_administrator",
    ),
    _made_here(BIBER_DN, "biber", "/home/biber"),
    {"dn": "uid=foreign,ou=users,dc=x", "uid": ["foreign", "extra"]},
]
LEGACY_GROUPS = [
    {"dn": ADMIN_GROUP, "member": [BIBER_DN, OLD_DN]},
    {"dn": POSIX_GROUP, "memberUid": "platform_administrator"},
    {"dn": EDITOR_GROUP, "member": BIBER_DN},
]


class TestLdapUserEntries(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    def test_user_entries_carry_what_the_create_task_set(self):
        entries = self.m.openldap_user_entries(
            USERS, "uid", "ou=users,dc=x", STRUCTURAL
        )
        self.assertEqual(
            entries[0],
            {
                "dn": "uid=alice,ou=users,dc=x",
                "attributes": {
                    "objectClass": STRUCTURAL,
                    "uid": "alice",
                    "givenName": "Alice",
                    "sn": "Liddell",
                    "cn": "Alice Liddell",
                    "loginShell": "/bin/bash",
                    "homeDirectory": "/home/alice",
                    "uidNumber": "1001",
                    "gidNumber": "1001",
                },
            },
        )
        self.assertEqual(entries[1]["attributes"]["cn"], "Bob B.")

    def test_a_user_keyed_apart_from_its_username_gets_one_uid_named_dn(self):
        users = {
            "platform_administrator": {**USERS["alice"], "username": "platformadmin"}
        }
        for build in (
            self.m.openldap_user_entries,
            self.m.openldap_user_class_entries,
            self.m.openldap_user_mail_entries,
        ):
            with self.subTest(build=build.__name__):
                entry = build(users, "uid", "ou=users,dc=x", STRUCTURAL)[0]
                self.assertEqual(entry["dn"], "uid=platformadmin,ou=users,dc=x")
                self.assertNotIn("platform_administrator", entry["dn"])
        attributes = self.m.openldap_user_entries(
            users, "uid", "ou=users,dc=x", STRUCTURAL
        )[0]["attributes"]
        self.assertEqual(attributes["uid"], "platformadmin")

    def test_the_password_entry_follows_the_username_named_dn(self):
        users = {
            "platform_administrator": {"username": "platformadmin", "password": "p"}
        }
        self.assertEqual(
            self.m.openldap_user_passwords(users, "uid", "ou=users,dc=x", []),
            [{"dn": "uid=platformadmin,ou=users,dc=x", "passwd": "p"}],
        )

    def test_cn_falls_back_to_the_key_without_any_name(self):
        users = {
            "bot": {
                **USERS["alice"],
                "username": "bot",
                "firstname": "",
                "lastname": "",
            }
        }
        entries = self.m.openldap_user_entries(
            users, "uid", "ou=users,dc=x", STRUCTURAL
        )
        self.assertEqual(entries[0]["attributes"]["cn"], "bot")

    def test_an_undeclared_user_with_only_a_password_is_named_with_its_gaps(self):
        users = {
            **USERS,
            "sld": {
                "password": "s3cret-value",
                "email": "sld@example.org",
                "accounts": ["identity"],
                "forward": "",
            },
        }
        with self.assertRaises(AnsibleFilterError) as ctx:
            self.m.openldap_user_entries(users, "uid", "ou=users,dc=x", STRUCTURAL)
        message = str(ctx.exception)
        self.assertIn(
            "user 'sld' lacks username, firstname, lastname, uid, gid", message
        )
        self.assertNotIn("'alice'", message)
        self.assertNotIn("s3cret-value", message)

    def test_a_present_but_empty_field_still_builds_the_entry(self):
        users = {"carol": {**USERS["alice"], "username": "carol", "lastname": ""}}
        entries = self.m.openldap_user_entries(
            users, "uid", "ou=users,dc=x", STRUCTURAL
        )
        self.assertEqual(entries[0]["attributes"]["sn"], "")

    def test_mail_entries_keep_classes_and_mail(self):
        entries = self.m.openldap_user_mail_entries(
            USERS, "uid", "ou=users,dc=x", STRUCTURAL
        )
        self.assertEqual(
            entries[1],
            {
                "dn": "uid=bob,ou=users,dc=x",
                "attributes": {"objectClass": STRUCTURAL, "mail": "bob@example.org"},
            },
        )

    def test_class_entries_leave_mail_alone(self):
        entries = self.m.openldap_user_class_entries(
            USERS, "uid", "ou=users,dc=x", STRUCTURAL
        )
        self.assertEqual(
            entries[0],
            {
                "dn": "uid=alice,ou=users,dc=x",
                "attributes": {"objectClass": STRUCTURAL},
            },
        )

    def test_mailbox_entries_set_every_found_entry_to_its_mailbox(self):
        results = [
            {"dn": "uid=alice,ou=users,dc=x", "uid": "alice"},
            {"dn": "uid=carol,ou=users,dc=x", "uid": ["carol"]},
        ]
        self.assertEqual(
            self.m.openldap_mailbox_entries(results, "uid", "mail", "example.com"),
            [
                {
                    "dn": "uid=alice,ou=users,dc=x",
                    "attributes": {"mail": "alice@example.com"},
                },
                {
                    "dn": "uid=carol,ou=users,dc=x",
                    "attributes": {"mail": "carol@example.com"},
                },
            ],
        )

    def test_an_entry_whose_rdn_key_sits_beside_its_username_uses_the_username(self):
        self.assertEqual(
            self.m.openldap_mailbox_entries(
                [{"dn": "uid=a,ou=users,dc=x", "uid": ["a", "b"]}],
                "uid",
                "mail",
                "example.com",
            ),
            [{"dn": "uid=a,ou=users,dc=x", "attributes": {"mail": "b@example.com"}}],
        )

    def test_an_entry_without_one_login_fails_the_mailbox_layout(self):
        for result in (
            {"dn": "uid=a,ou=users,dc=x", "uid": ["b", "c"]},
            {"dn": "uid=a,ou=users,dc=x"},
        ):
            with self.subTest(result=result), self.assertRaises(AnsibleFilterError):
                self.m.openldap_mailbox_entries([result], "uid", "mail", "example.com")

    def test_secondary_entries_skip_empty_and_mailbox_domain_addresses(self):
        results = [
            {"dn": "uid=alice,ou=users,dc=x", "uid": "alice"},
            {"dn": "uid=bob,ou=users,dc=x", "uid": "bob"},
            {"dn": "uid=carol,ou=users,dc=x", "uid": "carol"},
            {"dn": "uid=dave,ou=users,dc=x", "uid": "dave"},
        ]
        addresses = {
            "alice": "alice@example.org",
            "bob": "bob@Example.com",
            "carol": "",
        }
        self.assertEqual(
            self.m.openldap_secondary_mail_entries(
                results, addresses, "uid", "infinitoSecondaryMail", "example.com"
            ),
            [
                {
                    "dn": "uid=alice,ou=users,dc=x",
                    "attributes": {"infinitoSecondaryMail": "alice@example.org"},
                }
            ],
        )

    def test_the_current_external_address_becomes_the_secondary_one(self):
        results = [
            {"dn": "uid=alice,ou=users,dc=x", "mail": "alice@example.org"},
            {"dn": "uid=bob,ou=users,dc=x", "mail": "bob@Example.com"},
            {"dn": "uid=carol,ou=users,dc=x"},
            {
                "dn": "uid=dave,ou=users,dc=x",
                "mail": ["dave@example.com", "", "dave@example.net", "d@example.org"],
            },
            {"dn": "uid=erin,ou=users,dc=x", "mail": ""},
        ]
        self.assertEqual(
            self.m.openldap_current_mail_secondary_entries(
                results, "mail", "infinitoSecondaryMail", "example.com"
            ),
            [
                {
                    "dn": "uid=alice,ou=users,dc=x",
                    "attributes": {"infinitoSecondaryMail": "alice@example.org"},
                },
                {
                    "dn": "uid=dave,ou=users,dc=x",
                    "attributes": {"infinitoSecondaryMail": "dave@example.net"},
                },
            ],
        )

    def test_passwords_are_managed_unless_the_user_opts_out(self):
        users = {
            "alice": {"username": "alice", "password": "a-pw"},
            "bob": {"username": "bob", "password": "b-pw", "password_update": False},
            "carol": {
                "username": "carol",
                "password": "c-pw",
                "password_update": "false",
            },
            "dave": {"username": "dave", "password": "d-pw", "password_update": "yes"},
        }
        entries = self.m.openldap_user_passwords(users, "uid", "ou=users,dc=x", [])
        self.assertEqual(
            entries,
            [
                {"dn": "uid=alice,ou=users,dc=x", "passwd": "a-pw"},
                {"dn": "uid=dave,ou=users,dc=x", "passwd": "d-pw"},
            ],
        )

    def test_an_opted_out_user_created_by_this_run_still_gets_its_password(self):
        users = {
            "bob": {"username": "bob", "password": "b-pw", "password_update": False},
            "carol": {
                "username": "carol",
                "password": "c-pw",
                "password_update": False,
            },
        }
        entries = self.m.openldap_user_passwords(
            users, "uid", "ou=users,dc=x", ["uid=carol,ou=users,dc=x"]
        )
        self.assertEqual(entries, [{"dn": "uid=carol,ou=users,dc=x", "passwd": "c-pw"}])

    def _renames(self, entries, groups, users=None):
        return self.m.openldap_user_renames(
            RENAME_USERS if users is None else users,
            entries,
            groups,
            "uid",
            USERS_DN,
            STRUCTURAL,
            ["member", "uniqueMember"],
            ["memberUid"],
        )

    def _move_only(self, dn, login):
        return [{"dn": dn, "new_rdn": f"uid={login}", "move": True, "references": []}]

    def test_an_entry_created_under_an_earlier_username_still_moves(self):
        entries = [
            _made_here(
                OLD_DN,
                ["platformadministrator", "platform_administrator"],
                "/home/platform_administrator",
            )
        ]
        self.assertEqual(
            self._renames(entries, []), self._move_only(OLD_DN, "platformadmin")
        )

    def test_a_user_renamed_in_the_inventory_moves_to_the_new_username(self):
        dn = "uid=alice,ou=users,dc=x"
        entries = [_made_here(dn, "alice", "/home/alice")]
        self.assertEqual(
            self._renames(entries, [], {"alice": {"username": "alicia"}}),
            self._move_only(dn, "alicia"),
        )

    def test_group_values_wait_until_the_username_named_entry_exists(self):
        groups = [{"dn": ADMIN_GROUP, "member": [BIBER_DN, OLD_DN]}]
        self.assertEqual(self._renames([], groups), [])
        self.assertEqual(
            self._renames([_made_here(NEW_DN, "platformadmin", "/home/x")], groups),
            [
                {
                    "dn": OLD_DN,
                    "new_rdn": "uid=platformadmin",
                    "move": False,
                    "references": [
                        {
                            "dn": ADMIN_GROUP,
                            "attribute": "member",
                            "old": OLD_DN,
                            "new": NEW_DN,
                        }
                    ],
                }
            ],
        )

    def test_login_entries_leave_every_user_only_its_username(self):
        self.assertEqual(
            self.m.openldap_user_login_entries(RENAME_USERS, "uid", USERS_DN),
            [
                {"dn": NEW_DN, "attributes": {"uid": "platformadmin"}},
                {"dn": BIBER_DN, "attributes": {"uid": "biber"}},
            ],
        )

    def test_the_entry_named_by_its_key_moves_and_its_group_values_follow(self):
        self.assertEqual(
            self._renames(LEGACY_ENTRIES, LEGACY_GROUPS),
            [
                {
                    "dn": OLD_DN,
                    "new_rdn": "uid=platformadmin",
                    "move": True,
                    "references": [
                        {
                            "dn": ADMIN_GROUP,
                            "attribute": "member",
                            "old": OLD_DN,
                            "new": NEW_DN,
                        },
                        {
                            "dn": POSIX_GROUP,
                            "attribute": "memberUid",
                            "old": "platform_administrator",
                            "new": "platformadmin",
                        },
                    ],
                }
            ],
        )

    def test_a_foreign_entry_with_an_extra_uid_value_is_left_alone(self):
        entries = [
            {"dn": NEW_DN, "uid": "platformadmin"},
            {"dn": BIBER_DN, "uid": "biber"},
            {"dn": "uid=foreign,ou=users,dc=x", "uid": ["foreign", "extra"]},
            {"dn": "uid=other,ou=users,dc=x", "uid": ["other", "a", "b"]},
        ]
        self.assertEqual(self._renames(entries, []), [])

    def test_a_clean_directory_plans_nothing(self):
        entries = [
            {"dn": NEW_DN, "uid": "platformadmin"},
            {"dn": BIBER_DN, "uid": "biber"},
        ]
        groups = [
            {"dn": ADMIN_GROUP, "member": [BIBER_DN, NEW_DN]},
            {"dn": POSIX_GROUP, "memberUid": "platformadmin"},
        ]
        self.assertEqual(self._renames(entries, groups), [])

    def test_group_values_left_behind_after_the_move_are_still_repaired(self):
        entries = [{"dn": NEW_DN, "uid": "platformadmin"}]
        groups = [
            {"dn": ADMIN_GROUP, "member": [BIBER_DN, NEW_DN]},
            {"dn": POSIX_GROUP, "memberUid": ["biber", "platform_administrator"]},
            {
                "dn": EDITOR_GROUP,
                "uniqueMember": "UID=platform_administrator, ou=users,dc=x",
            },
        ]
        self.assertEqual(
            self._renames(entries, groups),
            [
                {
                    "dn": OLD_DN,
                    "new_rdn": "uid=platformadmin",
                    "move": False,
                    "references": [
                        {
                            "dn": EDITOR_GROUP,
                            "attribute": "uniqueMember",
                            "old": "UID=platform_administrator, ou=users,dc=x",
                            "new": NEW_DN,
                        },
                        {
                            "dn": POSIX_GROUP,
                            "attribute": "memberUid",
                            "old": "platform_administrator",
                            "new": "platformadmin",
                        },
                    ],
                }
            ],
        )

    def test_a_foreign_entry_at_the_old_dn_fails_instead_of_moving(self):
        for entry in (
            {
                "dn": OLD_DN,
                "uid": ["platformadmin", "platform_administrator"],
                "objectClass": ["top", "person", "inetOrgPerson"],
            },
            _made_here(
                OLD_DN,
                ["platformadmin", "platform_administrator"],
                "/home/intruder",
            ),
        ):
            with (
                self.subTest(entry=entry),
                self.assertRaises(AnsibleFilterError) as ctx,
            ):
                self._renames([entry], [])
            self.assertIn(OLD_DN, str(ctx.exception))

    def test_a_key_that_is_another_users_username_is_left_to_that_user(self):
        users = {
            **RENAME_USERS,
            "keeper": {"username": "platform_administrator"},
        }
        entries = [_made_here(OLD_DN, ["platform_administrator"], "/home/keeper")]
        self.assertEqual(self._renames(entries, LEGACY_GROUPS, users), [])
        with self.assertRaises(AnsibleFilterError):
            self._renames(LEGACY_ENTRIES, [], users)

    def test_an_entry_at_both_dns_fails_instead_of_merging(self):
        entries = [*LEGACY_ENTRIES, {"dn": "UID=platformadmin, ou=users,dc=x"}]
        with self.assertRaises(AnsibleFilterError) as ctx:
            self._renames(entries, [])
        self.assertIn(NEW_DN, str(ctx.exception))

    def test_dn_entries_share_one_attribute_set(self):
        entries = self.m.ldap_dn_entries(["a", "b"], {"objectClass": ["x"]})
        self.assertEqual(
            entries,
            [
                {"dn": "a", "attributes": {"objectClass": ["x"]}},
                {"dn": "b", "attributes": {"objectClass": ["x"]}},
            ],
        )


if __name__ == "__main__":
    unittest.main()
