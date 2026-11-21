from __future__ import annotations

import json
import unittest

from . import PROJECT_ROOT
from ._fake_frappe import FakeFrappe, run_script

SCRIPT = PROJECT_ROOT / "roles/web-app-erpnext/files/python/apply/rounding.py"
SYSTEM = "System Settings"
ACCOUNTS = "Accounts Settings"
BANKERS = "Banker's Rounding"
LEGACY = "Banker's Rounding (legacy)"
COMMERCIAL = "Commercial Rounding"


def _env(mode, method=BANKERS, row_wise_tax=0):
    return {
        "SITE_NAME": "next.erp.infinito.example",
        "ROUNDING_MODE": mode,
        "SYSTEM_ROUNDING": json.dumps({"rounding_method": method}),
        "ACCOUNTS_ROUNDING": json.dumps({"round_row_wise_tax": row_wise_tax}),
    }


class TestRounding(unittest.TestCase):
    def setUp(self) -> None:
        self.frappe = FakeFrappe()
        self.frappe.singles[SYSTEM] = {
            "rounding_method": LEGACY,
            "setup_complete": 1,
            "disable_user_pass_login": 1,
        }
        self.frappe.singles[ACCOUNTS] = {
            "round_row_wise_tax": 1,
            "allow_stale": 1,
        }

    def _run(self, mode, **values):
        printed = run_script(SCRIPT, self.frappe, _env(mode, **values))
        return json.loads(printed.strip().splitlines()[-1])

    def _stored(self):
        return (
            self.frappe.singles[SYSTEM]["rounding_method"],
            self.frappe.singles[ACCOUNTS]["round_row_wise_tax"],
        )

    def test_read_prints_what_the_site_holds_per_form_and_writes_nothing(
        self,
    ) -> None:
        result = self._run("read")

        self.assertEqual(
            {
                "system_rounding": {"rounding_method": LEGACY},
                "accounts_rounding": {"round_row_wise_tax": 1},
            },
            result,
        )
        self.assertEqual((LEGACY, 1), self._stored())
        self.assertEqual([], self.frappe.saved)
        self.assertFalse(self.frappe.db.committed)

    def test_converge_pins_bankers_rounding_and_tax_rounded_per_document(
        self,
    ) -> None:
        result = self._run("converge")

        self.assertEqual((BANKERS, 0), self._stored())
        self.assertEqual(
            [f"{SYSTEM}::rounding_method", f"{ACCOUNTS}::round_row_wise_tax"],
            result["changed"],
        )
        self.assertTrue(self.frappe.db.committed)
        self.assertIn(("clear_cache",), self.frappe.calls)

    def test_a_fresh_site_without_stored_values_gets_both_pins(self) -> None:
        self.frappe.singles = {}

        self._run("converge")

        self.assertEqual((BANKERS, 0), self._stored())

    def test_the_system_settings_are_saved_as_a_document_keeping_other_fields(
        self,
    ) -> None:
        self._run("converge")

        self.assertEqual([SYSTEM], self.frappe.saved)
        self.assertNotIn(
            ("set_single_value", SYSTEM, "rounding_method"), self.frappe.calls
        )
        self.assertEqual(1, self.frappe.singles[SYSTEM]["setup_complete"])
        self.assertEqual(1, self.frappe.singles[SYSTEM]["disable_user_pass_login"])

    def test_the_accounts_settings_write_only_the_pinned_field(self) -> None:
        self._run("converge")

        self.assertIn(
            ("set_single_value", ACCOUNTS, "round_row_wise_tax"), self.frappe.calls
        )
        self.assertNotIn(ACCOUNTS, self.frappe.saved)
        self.assertEqual(1, self.frappe.singles[ACCOUNTS]["allow_stale"])

    def test_aligned_settings_are_left_untouched(self) -> None:
        self.frappe.singles[SYSTEM]["rounding_method"] = BANKERS
        self.frappe.singles[ACCOUNTS]["round_row_wise_tax"] = 0

        result = self._run("converge")

        self.assertEqual([], result["changed"])
        self.assertEqual([], self.frappe.saved)
        self.assertNotIn("set_single_value", [call[0] for call in self.frappe.calls])
        self.assertFalse(self.frappe.db.committed)

    def test_a_second_run_writes_nothing(self) -> None:
        self._run("converge")
        self.frappe.saved.clear()
        self.frappe.db.committed = False

        result = self._run("converge")

        self.assertEqual([], result["changed"])
        self.assertEqual([], self.frappe.saved)
        self.assertFalse(self.frappe.db.committed)

    def test_only_the_drifted_doctype_is_written(self) -> None:
        self.frappe.singles[SYSTEM]["rounding_method"] = BANKERS

        result = self._run("converge")

        self.assertEqual([f"{ACCOUNTS}::round_row_wise_tax"], result["changed"])
        self.assertEqual([], self.frappe.saved)

    def test_the_values_come_from_the_inventory_not_the_script(self) -> None:
        result = self._run("converge", method=COMMERCIAL, row_wise_tax=1)

        self.assertEqual((COMMERCIAL, 1), self._stored())
        self.assertEqual([f"{SYSTEM}::rounding_method"], result["changed"])

    def test_an_unknown_mode_fails_before_frappe_starts(self) -> None:
        with self.assertRaisesRegex(ValueError, "ROUNDING_MODE"):
            self._run("write")

        self.assertEqual([], self.frappe.calls)

    def test_closes_the_site_after_each_mode(self) -> None:
        for mode in ("read", "converge"):
            with self.subTest(mode=mode):
                self._run(mode)

                self.assertEqual(("destroy",), self.frappe.calls[-1])


if __name__ == "__main__":
    unittest.main()
