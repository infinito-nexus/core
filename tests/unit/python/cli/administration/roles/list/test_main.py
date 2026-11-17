from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import cli.administration.roles.list.__main__ as list_main
from cli.administration.roles.marker import MARKER_FILE, marker_text

ORIGIN = "https://example.invalid/w.git ansible/roles/web-app-cst-a @ v1 (commit abc)"


class TestListMain(unittest.TestCase):
    def test_prints_each_placed_role_with_source_and_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            marker = roles / "web-app-cst-a" / MARKER_FILE
            marker.parent.mkdir()
            marker.write_text(
                marker_text("web-app-cst-a", "web-app-cst-a", ORIGIN, "1.0.0"),
                encoding="utf-8",
            )
            (roles / "web-app-cst-hand").mkdir()
            (roles / "web-app-nextcloud").mkdir()
            with (
                unittest.mock.patch.object(list_main, "ROLES_DIR", roles),
                contextlib.redirect_stdout(io.StringIO()) as out,
            ):
                self.assertEqual(0, list_main.main([]))
        self.assertEqual(f"web-app-cst-a: {ORIGIN}\n", out.getvalue())


if __name__ == "__main__":
    unittest.main()
