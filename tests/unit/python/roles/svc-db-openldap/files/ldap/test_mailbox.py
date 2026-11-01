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
            self.mod.sole_login(DN, ["biber", "beaver"], "uid")

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
