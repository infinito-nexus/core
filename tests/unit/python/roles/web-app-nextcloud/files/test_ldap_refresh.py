import contextlib
import io
import json
import subprocess
import sys
import types
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "web-app-nextcloud"
    / "files"
    / "python"
    / "ldap_refresh.py"
)
LDAP_CLIENT_DIR = PROJECT_ROOT / "roles" / "svc-db-openldap" / "files" / "python"
PREFIX = [
    "/usr/bin/container",
    "exec",
    "-i",
    "--user",
    "www-data",
    "c1",
    "php",
    "/var/www/html/occ",
]
LDAP = {
    "uri": "ldap://127.0.0.1:389",
    "users_dn": "ou=users,dc=example,dc=org",
    "roles_dn": "ou=roles,dc=example,dc=org",
    "attributes": {"id": "uid", "mail": "mail", "name": "cn", "member_of": "memberOf"},
}
PARTS = ["street", "postalCode", "l", "st", "c"]


def load_module():
    if str(LDAP_CLIENT_DIR) not in sys.path:
        sys.path.insert(0, str(LDAP_CLIENT_DIR))
    module = types.ModuleType("nextcloud_ldap_refresh")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


class FakeDirectory:
    def __init__(self, entries):
        self.entries = entries
        self.closed = False
        self.searches = []

    def search(self, base, scope, search_filter, attributes):
        self.searches.append((base, attributes))
        return self.entries

    def close(self):
        self.closed = True


class FakeOcc:
    def __init__(self, known, addresses):
        self.known = known
        self.addresses = dict(addresses)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        args = argv[len(PREFIX) :]
        stdout = ""
        if args[0] == "user:list":
            stdout = json.dumps(self.known)
        elif args[0] == "user:profile" and args[3].startswith("--default-value"):
            stdout = self.addresses.get(args[1], "") + "\n"
        elif args[0] == "user:profile":
            self.addresses[args[1]] = args[3]
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


def entry(uid, **parts):
    return (
        f"uid={uid},ou=users,dc=example,dc=org",
        {"uid": [uid], **{key.lower(): [value] for key, value in parts.items()}},
    )


class NextcloudLdapRefreshTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def run_main(self, known, directory, entries, addresses=None):
        environ = {
            "RBAC_SYNC_CONTAINER_BIN": "/usr/bin/container",
            "RBAC_SYNC_CID": "c1",
            "RBAC_SYNC_LDAP": json.dumps(LDAP),
            "NEXTCLOUD_USER": "www-data",
            "NEXTCLOUD_OCC": "/var/www/html/occ",
            "NEXTCLOUD_ADDRESS_ATTRIBUTES": json.dumps(PARTS),
            "RBAC_USERS": json.dumps(
                [{"username": name, "email": "", "name": ""} for name in directory]
            ),
        }
        occ = FakeOcc(known, addresses or {})
        ldap = FakeDirectory(entries)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.mod.main(environ, run=occ, connect=lambda uri: ldap)
        return occ, ldap, stdout.getvalue().strip().splitlines()

    def test_only_accounts_nextcloud_knows_are_refreshed(self):
        occ, ldap, output = self.run_main(
            {"alice": "Alice", "admin": "admin", "bob": "Bob"},
            ["bob", "alice", "carol"],
            [],
        )

        self.assertEqual(
            occ.calls,
            [
                [*PREFIX, "user:list", "--output=json", "--limit=0"],
                [*PREFIX, "ldap:check-user", "--update", "alice"],
                [*PREFIX, "ldap:check-user", "--update", "bob"],
            ],
        )
        self.assertEqual(output, ["REFRESHED 2"])
        self.assertTrue(ldap.closed)
        self.assertEqual(
            ldap.searches, [("ou=users,dc=example,dc=org", ["uid", *PARTS])]
        )

    def test_the_composed_address_is_written_only_where_it_differs(self):
        occ, _, output = self.run_main(
            {"alice": "Alice", "bob": "Bob"},
            ["alice", "bob"],
            [
                entry(
                    "alice",
                    street="Main St 1",
                    postalCode="10115",
                    l="Berlin",
                    st="BE",
                    c="DE",
                ),
                entry("bob", street="Side Rd 2", c="NL"),
            ],
            {"bob": "Side Rd 2, NL"},
        )

        self.assertEqual(occ.addresses["alice"], "Main St 1, 10115 Berlin, BE, DE")
        self.assertIn(
            [
                *PREFIX,
                "user:profile",
                "alice",
                "address",
                "Main St 1, 10115 Berlin, BE, DE",
            ],
            occ.calls,
        )
        self.assertNotIn(
            [*PREFIX, "user:profile", "bob", "address", "Side Rd 2, NL"], occ.calls
        )
        self.assertEqual(output, ["CHANGED alice address", "REFRESHED 2"])

    def test_an_account_without_a_directory_entry_keeps_its_address(self):
        occ, _, output = self.run_main(
            {"alice": "Alice"}, ["alice"], [], {"alice": "Kept 1"}
        )

        self.assertEqual(occ.addresses["alice"], "Kept 1")
        self.assertEqual(output, ["REFRESHED 1"])

    def test_empty_parts_leave_no_separator_behind(self):
        self.assertEqual(
            self.mod.compose_address("", "", "Berlin", "", "DE"), "Berlin, DE"
        )
        self.assertEqual(self.mod.compose_address("", "", "", "", ""), "")

    def test_a_failing_refresh_stops_the_hook(self):
        def failing(argv, **kwargs):
            if "ldap:check-user" in argv:
                raise subprocess.CalledProcessError(1, argv)
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps({"alice": "A"}), stderr=""
            )

        environ = {
            "RBAC_SYNC_CONTAINER_BIN": "/c",
            "RBAC_SYNC_CID": "c1",
            "RBAC_SYNC_LDAP": json.dumps(LDAP),
            "NEXTCLOUD_USER": "www-data",
            "NEXTCLOUD_OCC": "occ",
            "NEXTCLOUD_ADDRESS_ATTRIBUTES": json.dumps(PARTS),
            "RBAC_USERS": json.dumps([{"username": "alice", "email": "", "name": ""}]),
        }
        with self.assertRaises(subprocess.CalledProcessError):
            self.mod.main(environ, run=failing, connect=lambda uri: FakeDirectory([]))


if __name__ == "__main__":
    unittest.main()
