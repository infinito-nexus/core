"""Negative controls for the self-expiring container hard repair removal guard."""

from __future__ import annotations

import datetime as dt
import unittest

from tests.lint.ansible.variables import test_removed_names

lint = test_removed_names.ContainerHardRepair

OTHER = "roles/sys-ctl-hlth-container/tasks/00_core.yml"
UNIT_STEM, FLAG_STEM, *VARIABLES = lint.NAMES
RETIREMENT_LINE = f'{lint.RETIREMENT_KEY} "{lint.ROLE}"\n'
REMOVED_NOTE = f"- *{lint.ROLE}*, superseded by *sys-ctl-rpr-container-soft*.\n"


class TestNamed(unittest.TestCase):
    def test_the_role_include_is_found(self) -> None:
        text = f"list_or_shoot_roles:\n  - {lint.ROLE}\n"
        self.assertEqual([(2, UNIT_STEM)], lint.named(OTHER, text))

    def test_a_versioned_unit_name_is_found(self) -> None:
        text = f"systemctl start {UNIT_STEM}.1.2.3.infinito.nexus.timer\n"
        self.assertEqual([(1, UNIT_STEM)], lint.named(OTHER, text))

    def test_the_run_once_flag_is_found(self) -> None:
        text = f"when: run_once_sys_ctl_{FLAG_STEM} is not defined\n"
        self.assertEqual([(1, FLAG_STEM)], lint.named(OTHER, text))

    def test_every_removed_variable_is_found(self) -> None:
        self.assertEqual(3, len(VARIABLES))
        for name in VARIABLES:
            with self.subTest(name=name):
                self.assertEqual(
                    [(1, name)], lint.named("group_vars/all/x.yml", f"{name}: x\n")
                )

    def test_the_soft_repair_is_not_found(self) -> None:
        text = (
            "SYS_SERVICE_REPAIR_CONTAINER_SOFT: x\n"
            "SYS_TIMEOUT_CONTAINER_RPR_SOFT: 10min\n"
            "name: sys-ctl-rpr-container-soft\n"
        )
        self.assertEqual([], lint.named(OTHER, text))

    def test_the_retirement_line_is_exempt(self) -> None:
        self.assertEqual([], lint.named(lint.RETIREMENT_VARS, RETIREMENT_LINE))

    def test_the_retirement_key_elsewhere_is_found(self) -> None:
        self.assertEqual([(1, UNIT_STEM)], lint.named(OTHER, RETIREMENT_LINE))

    def test_another_line_of_the_retirement_file_is_found(self) -> None:
        name = VARIABLES[1]
        self.assertEqual([(1, name)], lint.named(lint.RETIREMENT_VARS, f"{name}: x\n"))


class TestFindings(unittest.TestCase):
    def test_a_release_note_naming_the_role_passes(self) -> None:
        for rel in (
            "CHANGELOG.md",
            "packaging/debian/changelog",
            "packaging/fedora/infinito-nexus.spec",
        ):
            with self.subTest(rel=rel):
                self.assertEqual([], lint.findings(rel, REMOVED_NOTE))

    def test_the_same_line_in_a_role_file_fails(self) -> None:
        self.assertEqual([(1, UNIT_STEM)], lint.findings(OTHER, REMOVED_NOTE))

    def test_a_packaging_script_is_still_scanned(self) -> None:
        self.assertEqual(
            [(1, UNIT_STEM)], lint.findings("packaging/debian/postinst", REMOVED_NOTE)
        )

    def test_the_catalogs_and_the_retirement_test_are_skipped(self) -> None:
        for rel in ("locale/de/LC_MESSAGES/core.po", lint.RETIREMENT_TEST):
            with self.subTest(rel=rel):
                self.assertEqual([], lint.findings(rel, REMOVED_NOTE))


class TestExpiry(unittest.TestCase):
    def test_the_day_before_the_sunset_is_live(self) -> None:
        self.assertFalse(lint.expired(lint.SUNSET - dt.timedelta(days=1)))

    def test_the_sunset_day_expires_the_guard(self) -> None:
        self.assertTrue(lint.expired(lint.SUNSET))

    def test_the_sunset_is_the_agreed_date(self) -> None:
        self.assertEqual(dt.date(2027, 2, 5), lint.SUNSET)


if __name__ == "__main__":
    unittest.main()
