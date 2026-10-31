from __future__ import annotations

import datetime as dt
import json
import unittest
from types import SimpleNamespace

from . import PROJECT_ROOT
from ._fake_frappe import FakeFrappe, LinkValidationError, run_script

SCRIPT = PROJECT_ROOT / "roles/web-app-erpnext/files/python/apply/company.py"
COMPANY = "Infinito.Nexus"
TAX_ACCOUNTS = ("VAT 19%", "VAT 7%", "VAT 20%", "Reverse Charge", "Export")


def _env(**overrides):
    return {
        "SITE_NAME": "next.erp.infinito.example",
        "COMPANY_NAME": COMPANY,
        "COMPANY_ABBR": "IN",
        "COMPANY_COUNTRY": "Germany",
        **overrides,
    }


def _seed_company(frappe, name, abbr, **values):
    frappe.seed(
        "Company",
        name,
        company_name=name,
        abbr=abbr,
        country=values.pop("country", "United States"),
        default_currency=values.pop("default_currency", "USD"),
        **values,
    )
    frappe.seed(
        "Account",
        f"Duties and Taxes - {abbr}",
        company=name,
        account_type="Tax",
        is_group=1,
        lft=30,
    )


class TestCompany(unittest.TestCase):
    def setUp(self) -> None:
        self.frappe = FakeFrappe()

    def _run(self, **overrides):
        printed = run_script(SCRIPT, self.frappe, _env(**overrides))
        return json.loads(printed.strip().splitlines()[-1])

    def _company(self, name=COMPANY):
        return self.frappe.records["Company"][name]

    def test_creates_company_with_the_currency_its_country_uses(self) -> None:
        self._run()

        company = self._company()
        self.assertEqual(company["abbr"], "IN")
        self.assertEqual(company["country"], "Germany")
        self.assertEqual(company["default_currency"], "EUR")

    def test_reports_the_company_and_its_currency(self) -> None:
        result = self._run()

        self.assertEqual(result["company"], COMPANY)
        self.assertEqual(result["abbr"], "IN")
        self.assertEqual(result["country"], "Germany")
        self.assertEqual(result["currency"], "EUR")
        self.assertIn(f"Company: {COMPANY}", result["created"])

    def test_creates_the_records_the_skipped_setup_wizard_would(self) -> None:
        self._run()

        records = self.frappe.records
        self.assertIn("Transit", records["Warehouse Type"])
        self.assertEqual(records["Territory"]["All Territories"]["is_group"], 1)
        self.assertIn("Unit", records["UOM"])
        self.assertIn("Sales", records["Opportunity Type"])

    def test_creates_a_fiscal_year_covering_today(self) -> None:
        self._run()

        fiscal_year = self.frappe.records["Fiscal Year"]["2026"]
        self.assertEqual(fiscal_year["year_start_date"], dt.date(2026, 1, 1))
        self.assertEqual(fiscal_year["year_end_date"], dt.date(2026, 12, 31))

    def test_reuses_a_fiscal_year_that_already_covers_today(self) -> None:
        self.frappe.seed(
            "Fiscal Year",
            "2026-2027",
            year="2026-2027",
            year_start_date=dt.date(2026, 4, 1),
            year_end_date=dt.date(2027, 3, 31),
            disabled=0,
        )

        self._run()

        self.assertEqual(list(self.frappe.records["Fiscal Year"]), ["2026-2027"])

    def test_ignores_a_fiscal_year_of_another_company(self) -> None:
        self.frappe.seed(
            "Fiscal Year",
            "2026 Other",
            year="2026 Other",
            year_start_date=dt.date(2026, 1, 1),
            year_end_date=dt.date(2026, 12, 31),
            disabled=0,
            companies=[SimpleNamespace(company="Other")],
        )

        self._run()

        self.assertIn("2026", self.frappe.records["Fiscal Year"])

    def test_creates_the_tax_accounts_under_duties_and_taxes(self) -> None:
        self._run()

        accounts = self.frappe.records["Account"]
        for account_name in TAX_ACCOUNTS:
            account = accounts[f"{account_name} - IN"]
            self.assertEqual(account["parent_account"], "Duties and Taxes - IN")
            self.assertEqual(account["account_type"], "Tax")
            self.assertEqual(account["is_group"], 0)
            self.assertEqual(account["company"], COMPANY)

    def test_makes_the_company_the_global_default_with_its_country_and_currency(
        self,
    ) -> None:
        self._run()

        defaults = self.frappe.singles["Global Defaults"]
        self.assertEqual(defaults["default_company"], COMPANY)
        self.assertEqual(defaults["country"], "Germany")
        self.assertEqual(defaults["default_currency"], "EUR")

    def test_keeps_a_global_default_company_that_is_already_set(self) -> None:
        self.frappe.singles["Global Defaults"] = {
            "default_company": "Other",
            "default_currency": "USD",
        }

        self._run()

        self.assertEqual(
            self.frappe.singles["Global Defaults"],
            {"default_company": "Other", "default_currency": "USD"},
        )

    def test_second_run_creates_nothing(self) -> None:
        self._run()
        before = json.dumps([self.frappe.records, self.frappe.singles], default=str)

        result = self._run()

        self.assertEqual(result["created"], [])
        self.assertEqual(
            json.dumps([self.frappe.records, self.frappe.singles], default=str), before
        )

    def test_existing_company_keeps_its_own_values(self) -> None:
        _seed_company(self.frappe, COMPANY, "XY", default_cash_account="Cash - XY")

        result = self._run()

        company = self._company()
        self.assertEqual(company["abbr"], "XY")
        self.assertEqual(company["country"], "United States")
        self.assertEqual(company["default_currency"], "USD")
        self.assertEqual(company["default_cash_account"], "Cash - XY")
        self.assertEqual(result["abbr"], "XY")
        self.assertNotIn(f"Company: {COMPANY}", result["created"])

    def test_existing_company_gets_tax_accounts_under_its_own_abbreviation(
        self,
    ) -> None:
        _seed_company(self.frappe, COMPANY, "XY", default_cash_account="Cash - XY")

        self._run()

        self.assertIn("VAT 19% - XY", self.frappe.records["Account"])
        self.assertNotIn("VAT 19% - IN", self.frappe.records["Account"])

    def test_fills_an_empty_cash_account_with_the_first_cash_leaf(self) -> None:
        _seed_company(self.frappe, COMPANY, "XY")
        self.frappe.seed(
            "Account",
            "Till - XY",
            company=COMPANY,
            account_type="Cash",
            is_group=0,
            lft=21,
        )
        self.frappe.seed(
            "Account",
            "Cash - XY",
            company=COMPANY,
            account_type="Cash",
            is_group=0,
            lft=20,
        )

        self._run()

        self.assertEqual(self._company()["default_cash_account"], "Cash - XY")

    def test_falls_back_to_a_bank_account_without_a_cash_leaf(self) -> None:
        _seed_company(self.frappe, COMPANY, "XY")
        self.frappe.seed(
            "Account",
            "Bank - XY",
            company=COMPANY,
            account_type="Bank",
            is_group=0,
            lft=40,
        )

        self._run()

        self.assertEqual(self._company()["default_cash_account"], "Bank - XY")

    def test_company_without_cash_or_bank_account_fails(self) -> None:
        _seed_company(self.frappe, COMPANY, "XY")

        with self.assertRaisesRegex(SystemExit, "neither a Cash nor a Bank account"):
            self._run()

    def test_company_without_a_tax_group_fails(self) -> None:
        self.frappe.seed(
            "Company",
            COMPANY,
            company_name=COMPANY,
            abbr="XY",
            country="Germany",
            default_currency="EUR",
            default_cash_account="Cash - XY",
        )

        with self.assertRaisesRegex(SystemExit, "Duties and Taxes - XY"):
            self._run()

    def test_abbreviation_of_another_company_fails(self) -> None:
        _seed_company(self.frappe, "Other", "IN", default_cash_account="Cash - IN")

        with self.assertRaises(LinkValidationError):
            self._run()

    def test_unknown_country_names_the_inventory_key_to_set(self) -> None:
        with self.assertRaisesRegex(
            SystemExit, "Nexusland.*service_provider.company.address.country"
        ):
            self._run(COMPANY_COUNTRY="Nexusland")

        self.assertEqual(self.frappe.calls, [])

    def test_empty_company_name_names_the_inventory_key_to_set(self) -> None:
        with self.assertRaisesRegex(SystemExit, "service_provider.company.titel"):
            self._run(COMPANY_NAME="  ")

    def test_empty_abbreviation_names_the_inventory_key_to_set(self) -> None:
        with self.assertRaisesRegex(
            SystemExit, "applications.web-app-erpnext.services.erpnext.company.abbr"
        ):
            self._run(COMPANY_ABBR="")

    def test_commits_and_closes_the_site(self) -> None:
        self._run()

        self.assertTrue(self.frappe.db.committed)
        self.assertEqual(self.frappe.calls[-1], ("destroy",))


if __name__ == "__main__":
    unittest.main()
