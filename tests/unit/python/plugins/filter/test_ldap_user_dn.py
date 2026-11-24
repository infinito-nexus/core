import unittest

from plugins.filter.ldap.user_dn import FilterModule, ldap_user_dn

USERS_DN = "ou=users,dc=example,dc=org"


class TestLdapUserDn(unittest.TestCase):
    def test_the_rdn_value_is_the_username(self):
        self.assertEqual(
            ldap_user_dn({"username": "biber"}, "uid", USERS_DN),
            "uid=biber,ou=users,dc=example,dc=org",
        )

    def test_a_user_keyed_apart_from_its_username_is_named_by_the_username(self):
        users = {"platform_administrator": {"username": "platformadmin"}}
        dn = ldap_user_dn(users["platform_administrator"], "uid", USERS_DN)
        self.assertEqual(dn, "uid=platformadmin,ou=users,dc=example,dc=org")
        self.assertNotIn("platform_administrator", dn)

    def test_a_record_without_username_fails_instead_of_guessing(self):
        with self.assertRaises(KeyError):
            ldap_user_dn({"firstname": "Platform"}, "uid", USERS_DN)

    def test_the_filter_is_registered(self):
        self.assertIs(FilterModule().filters()["ldap_user_dn"], ldap_user_dn)


if __name__ == "__main__":
    unittest.main()
