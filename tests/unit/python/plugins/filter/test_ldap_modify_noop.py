import unittest

from plugins.filter.ldap_modify_noop import ldap_modify_noop


class TestLdapModifyNoop(unittest.TestCase):
    def test_idempotency_variants_are_noop(self):
        for stderr in (
            'modifying entry "cn=module{0},cn=config"\nldap_modify: Type or value exists (20)',
            "ldap_add: Already exists (68)",
            "ldap_modify: Duplicate value (20)",
            "ldap_modify: Duplicate attribute value",
        ):
            self.assertTrue(ldap_modify_noop(stderr))

    def test_real_errors_stay_false(self):
        for stderr in (
            "ldap_modify: Insufficient access (50)",
            "ldap_bind: Invalid credentials (49)",
            "ldap_modify: No such object (32)",
            "",
            None,
        ):
            self.assertFalse(ldap_modify_noop(stderr))


if __name__ == "__main__":
    unittest.main()
