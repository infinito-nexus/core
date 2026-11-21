import sys
import unittest

from .test_script import ALICE, ALICE_UUID, LDAP, StubDirectory, load_module


def reader_module():
    """Returns:
    the ``member_reader`` module, loaded the way the RBAC sync script imports it.
    """
    load_module()
    return sys.modules["member_reader"]


class DirectoryMembersTests(unittest.TestCase):
    def setUp(self):
        self.mod = reader_module()

    def test_members_take_the_first_value_and_are_sorted(self):
        group = "cn=web-app-weblate-reviewer,ou=roles,dc=example,dc=org"
        directory = StubDirectory(
            {
                group: [
                    ("uid=bob", {"uid": ["bob"], "mail": ["bob@example.org"]}),
                    (
                        "uid=alice",
                        {
                            "uid": ["alice", "al"],
                            "mail": [ALICE["email"]],
                            "cn": [ALICE["name"]],
                            "entryuuid": [ALICE_UUID],
                        },
                    ),
                    ("uid=ghost", {"mail": ["ghost@example.org"]}),
                ]
            }
        )

        members = self.mod.directory_members(
            directory, LDAP, "web-app-weblate", "reviewer", []
        )

        self.assertEqual(
            members,
            [
                ALICE,
                {"username": "bob", "email": "bob@example.org", "name": "", "uuid": ""},
            ],
        )
        self.assertEqual(directory.searches[0][0], LDAP["users_dn"])
        self.assertEqual(directory.searches[0][2], ["uid", "mail", "cn", "entryUUID"])

    def test_the_users_role_lists_every_account_with_a_login(self):
        mod = self.mod
        captured = []

        class Directory:
            def search(self, base, scope, search_filter, attributes):
                captured.append(search_filter)
                return [("uid=carol", {"uid": ["carol"]})]

        members = mod.directory_members(
            Directory(), LDAP, "web-app-nextcloud", "@users", []
        )

        self.assertEqual(
            members, [{"username": "carol", "email": "", "name": "", "uuid": ""}]
        )
        self.assertEqual(captured, [mod.present("uid")])

    def test_a_users_role_with_an_attribute_lists_only_its_holders(self):
        captured = []

        class Directory:
            def search(self, base, scope, search_filter, attributes):
                captured.append(search_filter)
                return [("uid=carol", {"uid": ["carol"]})]

        self.mod.directory_members(
            Directory(), LDAP, "web-app-jellyfin", "@users:jpegPhoto", ["jpegPhoto"]
        )

        self.assertEqual(captured, [self.mod.present("jpegPhoto")])
        self.assertEqual(
            [
                self.mod.users_holding(role, "uid")
                for role in ("@users", "@users:jpegPhoto", "administrator")
            ],
            ["uid", "jpegPhoto", ""],
        )


class RoleGroupTests(unittest.TestCase):
    def setUp(self):
        self.mod = reader_module()

    def test_a_role_name_is_a_role_of_the_hooks_application(self):
        self.assertEqual(
            self.mod.role_group("web-app-erpnext", "manager"),
            ("web-app-erpnext", "manager"),
        )

    def test_a_group_path_names_a_role_of_another_application(self):
        for path in (
            "/roles/web-app-consumer/auditor",
            "roles/web-app-consumer/auditor/",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    self.mod.role_group("web-app-erpnext", path),
                    ("web-app-consumer", "auditor"),
                )

    def test_a_group_path_searches_the_group_of_its_application(self):
        group = "cn=web-app-consumer-auditor,ou=roles,dc=example,dc=org"
        directory = StubDirectory(
            {group: [("uid=alice", {"uid": ["alice"], "mail": [ALICE["email"]]})]}
        )

        members = self.mod.directory_members(
            directory,
            LDAP,
            *self.mod.role_group("web-app-erpnext", "/roles/web-app-consumer/auditor"),
            [],
        )

        self.assertEqual(
            members,
            [{"username": "alice", "email": ALICE["email"], "name": "", "uuid": ""}],
        )

    def test_a_path_of_another_shape_fails(self):
        for path in (
            "/roles/web-app-consumer",
            "/roles/web-app-consumer/t.example/auditor",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.mod.role_group("web-app-erpnext", path)


if __name__ == "__main__":
    unittest.main()
