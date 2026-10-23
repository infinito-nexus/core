import importlib.util
import unittest
from pathlib import Path

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
