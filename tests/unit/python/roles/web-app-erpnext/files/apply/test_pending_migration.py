from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from . import PROJECT_ROOT
from ._fake_frappe import FakeFrappe, run_script

SCRIPT = PROJECT_ROOT / "roles/web-app-erpnext/files/python/apply/pending_migration.py"
SITE = "next.erp.infinito.example"


class TestPendingMigration(unittest.TestCase):
    def setUp(self) -> None:
        self.frappe = FakeFrappe()

    def _record(self, **versions) -> None:
        self.frappe.singles["Installed Applications"] = {
            "installed_applications": [
                SimpleNamespace(app_name=app, app_version=version)
                for app, version in versions.items()
            ]
        }

    def _ship(self, **versions) -> None:
        self.frappe.apps_info = [
            {"app_name": app, "version": version} for app, version in versions.items()
        ]

    def _pending(self):
        printed = run_script(SCRIPT, self.frappe, {"SITE_NAME": SITE})
        return json.loads(printed.strip().splitlines()[-1])["pending"]

    def test_nothing_pending_when_recorded_matches_the_image(self) -> None:
        self._record(frappe="16.20.0", erpnext="16.54.0")
        self._ship(frappe="16.20.0", erpnext="16.54.0")

        self.assertEqual(self._pending(), [])

    def test_an_image_bump_without_migration_is_pending(self) -> None:
        self._record(frappe="16.20.0", erpnext="16.53.0")
        self._ship(frappe="16.20.0", erpnext="16.54.0")

        self.assertEqual(self._pending(), ["erpnext"])

    def test_an_app_the_site_never_recorded_is_pending(self) -> None:
        self._record(frappe="16.20.0")
        self._ship(frappe="16.20.0", erpnext="16.54.0")

        self.assertEqual(self._pending(), ["erpnext"])

    def test_an_app_without_a_version_matches_frappes_placeholder(self) -> None:
        self._record(custom="UNVERSIONED")
        self._ship(custom=None)

        self.assertEqual(self._pending(), [])

    def test_releases_compare_by_number_not_by_text(self) -> None:
        self._record(erpnext="16.9.0")
        self._ship(erpnext="16.10.0")

        self.assertEqual(self._pending(), ["erpnext"])

    def test_an_older_image_fails_instead_of_migrating_down(self) -> None:
        self._record(frappe="16.20.0", erpnext="16.54.0")
        self._ship(frappe="16.20.0", erpnext="16.53.0")

        with self.assertRaises(SystemExit) as raised:
            self._pending()

        self.assertIn("erpnext 16.53.0 < 16.54.0", str(raised.exception.code))

    def test_an_unparsable_version_still_migrates(self) -> None:
        self._record(custom="UNVERSIONED")
        self._ship(custom="1.0.0")

        self.assertEqual(self._pending(), ["custom"])

    def test_the_site_connection_closes(self) -> None:
        self._record(erpnext="16.54.0")
        self._ship(erpnext="16.54.0")

        self._pending()

        self.assertEqual(
            self.frappe.calls,
            [
                ("init", SITE, "/home/frappe/frappe-bench/sites"),
                ("connect",),
                ("destroy",),
            ],
        )


if __name__ == "__main__":
    unittest.main()
