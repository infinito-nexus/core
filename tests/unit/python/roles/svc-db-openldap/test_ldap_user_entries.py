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
                    "cn": "alice",
                    "loginShell": "/bin/bash",
                    "homeDirectory": "/home/alice",
                    "uidNumber": "1001",
                    "gidNumber": "1001",
                },
            },
        )
        self.assertEqual(entries[1]["attributes"]["cn"], "Bob B.")

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

    def test_passwords_are_managed_unless_the_user_opts_out(self):
        users = {
            "alice": {"password": "a-pw"},
            "bob": {"password": "b-pw", "password_update": False},
            "carol": {"password": "c-pw", "password_update": "false"},
            "dave": {"password": "d-pw", "password_update": "yes"},
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
            "bob": {"password": "b-pw", "password_update": False},
            "carol": {"password": "c-pw", "password_update": False},
        }
        entries = self.m.openldap_user_passwords(
            users, "uid", "ou=users,dc=x", ["uid=carol,ou=users,dc=x"]
        )
        self.assertEqual(entries, [{"dn": "uid=carol,ou=users,dc=x", "passwd": "c-pw"}])

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
