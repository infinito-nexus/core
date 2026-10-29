from __future__ import annotations

import contextlib
import io
import unittest
from unittest import mock

import cli.administration.roles.clean.__main__ as clean_main


class TestCleanMain(unittest.TestCase):
    def test_reports_the_roles_it_removed_and_the_entries_it_left(self):
        lines = [
            "web-app-cst-a: removed",
            "web-app-cst-hand: left in place, the pull did not place it",
        ]
        with (
            mock.patch.object(clean_main, "clean", return_value=lines) as clean,
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(0, clean_main.main([]))
        clean.assert_called_once_with(clean_main.ROLES_DIR, clean_main.WORK_DIR)
        self.assertEqual(
            "custom role web-app-cst-a: removed\n"
            "custom role web-app-cst-hand: left in place, the pull did not place it\n",
            out.getvalue(),
        )

    def test_a_filesystem_error_exits_with_it(self):
        with (
            mock.patch.object(clean_main, "clean", side_effect=OSError("busy")),
            self.assertRaises(SystemExit) as exit_,
        ):
            clean_main.main([])
        self.assertIn("busy", str(exit_.exception.code))


if __name__ == "__main__":
    unittest.main()
