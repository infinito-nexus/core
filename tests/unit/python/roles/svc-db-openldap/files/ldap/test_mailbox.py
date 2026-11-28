import types
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "svc-db-openldap"
    / "files"
    / "python"
    / "ldap"
    / "mailbox.py"
)
DN = "uid=biber,ou=users,dc=example,dc=org"


def load_module():
    module = types.ModuleType("ldap_mailbox")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


class LdapMailboxTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_the_one_login_is_returned(self):
        self.assertEqual(self.mod.sole_login(DN, ["biber"], "uid"), "biber")

    def test_several_logins_are_refused(self):
        with self.assertRaisesRegex(ValueError, "holds 2 values of uid"):
            self.mod.sole_login(DN, ["beaver", "otter"], "uid")

    def test_the_rdn_key_beside_the_username_yields_the_username(self):
        dn = "uid=platform_administrator,ou=users,dc=example,dc=org"
        for logins in (
            ["platformadmin", "platform_administrator"],
            ["Platform_Administrator", "platformadmin"],
        ):
            with self.subTest(logins=logins):
                self.assertEqual(
                    self.mod.sole_login(dn, logins, "uid"), "platformadmin"
                )

    def test_two_logins_beside_the_rdn_are_refused(self):
        dn = "uid=platform_administrator,ou=users,dc=example,dc=org"
        with self.assertRaisesRegex(ValueError, "holds 2 values of uid"):
            self.mod.sole_login(
                dn, ["platformadmin", "padmin", "platform_administrator"], "uid"
            )

    def test_no_login_is_refused(self):
        for logins in ([], [""]):
            with (
                self.subTest(logins=logins),
                self.assertRaisesRegex(ValueError, "holds no uid"),
            ):
                self.mod.sole_login(DN, logins, "uid")

    def test_the_mailbox_address_is_the_login_at_the_domain(self):
        self.assertEqual(
            self.mod.mailbox_address("biber", "example.org"), "biber@example.org"
        )


if __name__ == "__main__":
    unittest.main()
