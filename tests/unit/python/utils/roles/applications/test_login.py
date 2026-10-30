import unittest

from utils.roles.applications import login

MODES = {
    "sso": (True, True),
    "sso_without_ldap": (True, False),
    "ldap": (False, True),
    "native": (False, False),
}

EXPECTED_ON = {
    "sso": {"sso"},
    "sso_without_ldap": {"sso"},
    "ldap": {"ldap", "2fa"},
    "native": {"native", "2fa"},
}


class TestLoginMethodDefaults(unittest.TestCase):
    def test_every_mode_turns_on_exactly_its_methods(self):
        for mode, (sso, ldap) in MODES.items():
            for method in login.METHODS:
                with self.subTest(mode=mode, method=method):
                    self.assertIs(
                        login.default(method, sso, ldap),
                        method in EXPECTED_ON[mode],
                    )

    def test_an_unknown_method_is_refused(self):
        with self.assertRaises(ValueError):
            login.default("magic", False, False)


if __name__ == "__main__":
    unittest.main()
