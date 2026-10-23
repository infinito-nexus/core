from __future__ import annotations

import unittest
from types import SimpleNamespace

from . import PROJECT_ROOT
from ._fake_frappe import FakeFrappe, run_script

SCRIPT = PROJECT_ROOT / "roles/web-app-erpnext/files/python/apply/api_bot.py"
BOT_EMAIL = "erpnext-api-bot@infinito.example"


def _env(**overrides):
    return {
        "SITE_NAME": "next.erp.infinito.example",
        "API_BOT_LOGIN": "erpnext-api-bot",
        "API_BOT_EMAIL": BOT_EMAIL,
        "API_BOT_FIRSTNAME": "ERPNext",
        "API_BOT_LASTNAME": "API Bot",
        "API_BOT_PASSWORD": "bot-password",
        "API_KEY_SECRET": "keykeysecretsecret",
        "COUNTRY": "Germany",
        "CURRENCY": "EUR",
        **overrides,
    }


class TestApiBot(unittest.TestCase):
    def setUp(self) -> None:
        self.frappe = FakeFrappe()

    def _run(self, **overrides) -> None:
        run_script(SCRIPT, self.frappe, _env(**overrides))

    def test_fills_an_empty_system_country_and_currency(self) -> None:
        self._run()

        settings = self.frappe.singles["System Settings"]
        self.assertEqual(settings["country"], "Germany")
        self.assertEqual(settings["currency"], "EUR")

    def test_keeps_a_system_country_and_currency_already_set(self) -> None:
        self.frappe.singles["System Settings"] = {
            "country": "United States",
            "currency": "USD",
        }

        self._run()

        settings = self.frappe.singles["System Settings"]
        self.assertEqual(settings["country"], "United States")
        self.assertEqual(settings["currency"], "USD")

    def test_marks_the_setup_wizard_complete(self) -> None:
        self.frappe.tables.add("Installed Application")
        self.frappe.seed("Installed Application", "erpnext", is_setup_complete=0)
        self.frappe.defaults["desktop:home_page"] = "setup-wizard"

        self._run()

        self.assertEqual(self.frappe.defaults["setup_complete"], "1")
        self.assertEqual(self.frappe.singles["System Settings"]["setup_complete"], 1)
        self.assertEqual(
            self.frappe.records["Installed Application"]["erpnext"][
                "is_setup_complete"
            ],
            1,
        )
        self.assertEqual(self.frappe.defaults["desktop:home_page"], "")

    def test_creates_the_bot_as_system_manager_with_split_api_credentials(
        self,
    ) -> None:
        self._run()

        bot = self.frappe.records["User"][BOT_EMAIL]
        self.assertEqual(bot["username"], "erpnext-api-bot")
        self.assertEqual(bot["api_key"], "keykeysec")
        self.assertEqual(bot["api_secret"], "retsecret")
        self.assertEqual([row.role for row in bot["roles"]], ["System Manager"])

    def test_keeps_a_single_system_manager_role_on_an_existing_bot(self) -> None:
        self.frappe.seed(
            "User",
            BOT_EMAIL,
            email=BOT_EMAIL,
            roles=[SimpleNamespace(role="System Manager")],
        )

        self._run()

        roles = self.frappe.records["User"][BOT_EMAIL]["roles"]
        self.assertEqual([row.role for row in roles], ["System Manager"])

    def test_missing_currency_fails_before_touching_the_site(self) -> None:
        env = _env()
        del env["CURRENCY"]

        with self.assertRaises(KeyError):
            run_script(SCRIPT, self.frappe, env)

        self.assertEqual(self.frappe.calls, [])


if __name__ == "__main__":
    unittest.main()
