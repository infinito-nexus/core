import contextlib
import io
import sys
import types
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "web-app-homeassistant"
    / "files"
    / "python"
    / "ldap_login.py"
)
LDAP_CLIENT = (
    PROJECT_ROOT
    / "roles"
    / "svc-db-openldap"
    / "files"
    / "python"
    / "ldap"
    / "client.py"
)
USERS_DN = "ou=users,dc=example,dc=org"
ADMIN_GROUP = "cn=web-app-homeassistant-administrator,ou=roles,dc=example,dc=org"
USER_GROUP = "cn=web-app-homeassistant-user,ou=roles,dc=example,dc=org"
BIBER_DN = "uid=biber,ou=users,dc=example,dc=org"
ARGUMENTS = [
    "--uri",
    "ldap://openldap:389",
    "--users-dn",
    USERS_DN,
    "--login-attribute",
    "uid",
    "--display-attribute",
    "displayName",
    "--name-part-attribute",
    "givenName",
    "--name-part-attribute",
    "sn",
    "--admin-group",
    ADMIN_GROUP,
    "--user-group",
    USER_GROUP,
]


def load_module():
    if "ldap_client" not in sys.modules:
        sys.modules["ldap_client"] = types.ModuleType("ldap_client")
        exec(
            compile(read_text(str(LDAP_CLIENT)), str(LDAP_CLIENT), "exec"),
            sys.modules["ldap_client"].__dict__,
        )
    module = types.ModuleType("homeassistant_ldap_login")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


class StubDirectory:
    def __init__(self, mod, entries, password):
        self.mod = mod
        self.entries = entries
        self.password = password
        self.searches = []
        self.closed = False

    def search(self, base, scope, search_filter, attributes):
        self.searches.append((base, scope, search_filter, attributes))
        if scope == self.mod.SCOPE_ONE_LEVEL:
            return [(dn, {"uid": values["uid"]}) for dn, values in self.entries]
        return [(dn, values) for dn, values in self.entries if dn == base]

    def bind(self, dn, password):
        return self.mod.SUCCESS if password == self.password else 49

    def close(self):
        self.closed = True


def entry(member_of, **attributes):
    values = {"uid": ["biber"], "memberof": member_of}
    values.update({key.lower(): value for key, value in attributes.items()})
    return [(BIBER_DN, values)]


class LdapLoginDecisionTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.options = self.mod.parse_arguments(ARGUMENTS)

    def test_administrator_group_wins_over_user_group(self):
        self.assertEqual(
            self.mod.group_for([USER_GROUP, ADMIN_GROUP], ADMIN_GROUP, USER_GROUP),
            "system-admin",
        )

    def test_user_group_maps_to_system_users(self):
        self.assertEqual(
            self.mod.group_for([USER_GROUP], ADMIN_GROUP, USER_GROUP), "system-users"
        )

    def test_group_match_ignores_case_and_spacing(self):
        spaced = USER_GROUP.upper().replace(",", ", ")
        self.assertEqual(
            self.mod.group_for([spaced], ADMIN_GROUP, USER_GROUP), "system-users"
        )

    def test_no_role_group_is_refused(self):
        other = "cn=web-app-nextcloud-administrator,ou=roles,dc=example,dc=org"
        self.assertIsNone(self.mod.group_for([other], ADMIN_GROUP, USER_GROUP))

    def test_member_signs_in_with_display_name(self):
        directory = StubDirectory(
            self.mod, entry([ADMIN_GROUP], displayName=["Biber  Beaver"]), "secret"
        )

        self.assertEqual(
            self.mod.authenticate(directory, self.options, "biber", "secret"),
            ("Biber Beaver", "system-admin"),
        )

    def test_name_falls_back_to_name_parts(self):
        directory = StubDirectory(
            self.mod, entry([USER_GROUP], givenName=["Biber"], sn=["Beaver"]), "secret"
        )

        self.assertEqual(
            self.mod.authenticate(directory, self.options, "biber", "secret"),
            ("Biber Beaver", "system-users"),
        )

    def test_wrong_password_is_refused(self):
        directory = StubDirectory(self.mod, entry([ADMIN_GROUP]), "secret")

        self.assertIsNone(
            self.mod.authenticate(directory, self.options, "biber", "wrong")
        )

    def test_member_of_no_role_group_is_refused(self):
        directory = StubDirectory(self.mod, entry([]), "secret")

        self.assertIsNone(
            self.mod.authenticate(directory, self.options, "biber", "secret")
        )

    def test_differently_cased_login_is_refused(self):
        directory = StubDirectory(self.mod, entry([ADMIN_GROUP]), "secret")

        self.assertIsNone(
            self.mod.authenticate(directory, self.options, "Biber", "secret")
        )

    def test_empty_password_never_reaches_the_directory(self):
        directory = StubDirectory(self.mod, entry([ADMIN_GROUP]), "")

        self.assertIsNone(self.mod.authenticate(directory, self.options, "biber", ""))
        self.assertEqual(directory.searches, [])

    def test_ambiguous_login_is_refused(self):
        twice = [
            *entry([ADMIN_GROUP]),
            ("uid=biber,ou=other,dc=example,dc=org", {"uid": ["biber"]}),
        ]
        directory = StubDirectory(self.mod, twice, "secret")

        self.assertIsNone(
            self.mod.authenticate(directory, self.options, "biber", "secret")
        )


class LdapLoginMainTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def run_main(self, environ):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = self.mod.main(ARGUMENTS, environ)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_member_prints_name_and_group(self):
        directory = StubDirectory(
            self.mod, entry([USER_GROUP], displayName=["Biber"]), "secret"
        )
        self.mod.Connection = lambda uri: directory

        code, stdout, _ = self.run_main({"username": "biber", "password": "secret"})

        self.assertEqual(code, 0)
        self.assertEqual(stdout.splitlines(), ["name = Biber", "group = system-users"])
        self.assertTrue(directory.closed)

    def test_refusal_exits_one_without_output(self):
        directory = StubDirectory(self.mod, entry([]), "secret")
        self.mod.Connection = lambda uri: directory

        code, stdout, _ = self.run_main({"username": "biber", "password": "secret"})

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")

    def test_unreachable_directory_exits_one_without_the_password(self):
        def unreachable(uri):
            raise OSError("connection refused")

        self.mod.Connection = unreachable

        code, stdout, stderr = self.run_main(
            {"username": "biber", "password": "very-secret"}
        )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertNotIn("very-secret", stderr)


if __name__ == "__main__":
    unittest.main()
