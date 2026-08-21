import unittest

from plugins.filter.gitea_auth_noop import gitea_auth_noop


class TestGiteaAuthNoop(unittest.TestCase):
    def test_existing_source_is_noop(self):
        self.assertTrue(
            gitea_auth_noop("Command error: login source already exists [name: LDAP]")
        )
        self.assertTrue(gitea_auth_noop("LOGIN SOURCE ALREADY EXISTS"))

    def test_real_errors_stay_false(self):
        for stderr in (
            "Command error: failed to connect to LDAP server",
            "user already exists",
            "",
            None,
        ):
            self.assertFalse(gitea_auth_noop(stderr))


if __name__ == "__main__":
    unittest.main()
