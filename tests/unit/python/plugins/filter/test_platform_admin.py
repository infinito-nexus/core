import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.platform_admin import FilterModule

LOGIN = "platformadmin"
EMAIL = "platformadmin@example.org"
LEGACY = {"login": "administrator", "email": "administrator@example.org", "admin": True}


def account(login: str, email: str, admin: bool) -> dict:
    return {"login": login, "email": email, "admin": admin}


class TestPlatformAdminPlan(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = FilterModule().filters()["platform_admin_plan"]

    def test_absent_login_next_to_an_administrator_is_created(self) -> None:
        self.assertEqual(self.plan([LEGACY], LOGIN, EMAIL, "App", True), "create")

    def test_present_administrator_is_realigned(self) -> None:
        accounts = [LEGACY, account(LOGIN, EMAIL, True)]
        self.assertEqual(self.plan(accounts, LOGIN, EMAIL, "App", True), "realign")

    def test_present_administrator_is_realigned_even_when_its_email_differs(
        self,
    ) -> None:
        accounts = [
            account("other", EMAIL, True),
            account(LOGIN, "old@example.org", True),
        ]
        self.assertEqual(self.plan(accounts, LOGIN, EMAIL, "App", True), "realign")

    def test_app_without_administrator_fails(self) -> None:
        with self.assertRaisesRegex(AnsibleFilterError, "App has no administrator"):
            self.plan(
                [account("reader", "r@example.org", False)], LOGIN, EMAIL, "App", True
            )

    def test_app_without_any_account_fails(self) -> None:
        with self.assertRaisesRegex(AnsibleFilterError, "no administrator"):
            self.plan([], LOGIN, EMAIL, "App", True)

    def test_email_held_by_another_account_fails_naming_every_holder(self) -> None:
        accounts = [
            LEGACY,
            account("zed", "PlatformAdmin@Example.org", False),
            account("amy", EMAIL, True),
        ]
        with self.assertRaisesRegex(
            AnsibleFilterError, "held by the App account amy, zed"
        ):
            self.plan(accounts, LOGIN, EMAIL, "App", True)

    def test_non_administrator_holding_the_login_is_not_promoted(self) -> None:
        accounts = [LEGACY, account(LOGIN, EMAIL, False)]
        with self.assertRaisesRegex(AnsibleFilterError, "not promoted"):
            self.plan(accounts, LOGIN, EMAIL, "App", True)

    def test_case_insensitive_app_matches_the_login_in_any_case(self) -> None:
        accounts = [LEGACY, account("PlatformAdmin", EMAIL, False)]
        with self.assertRaisesRegex(
            AnsibleFilterError, "'PlatformAdmin' is no administrator"
        ):
            self.plan(accounts, LOGIN, EMAIL, "App", False)

    def test_case_sensitive_app_treats_another_case_as_another_login(self) -> None:
        accounts = [LEGACY, account("PlatformAdmin", "pa@example.org", False)]
        self.assertEqual(self.plan(accounts, LOGIN, EMAIL, "App", True), "create")

    def test_malformed_account_is_refused(self) -> None:
        with self.assertRaisesRegex(AnsibleFilterError, "boolean admin"):
            self.plan(
                [{"login": LOGIN, "email": EMAIL, "admin": "yes"}],
                LOGIN,
                EMAIL,
                "App",
                True,
            )

    def test_accounts_that_are_no_list_are_refused(self) -> None:
        with self.assertRaisesRegex(AnsibleFilterError, "as a list"):
            self.plan({"login": LOGIN}, LOGIN, EMAIL, "App", True)


if __name__ == "__main__":
    unittest.main()
