from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from cli.administration.roles.marker import (
    MARKER_FILE,
    custom_entries,
    is_placed,
    marker_text,
    placed_roles,
    provenance,
    write_marker,
)

from ._fixtures import write

ORIGIN = "https://example.invalid/w.git ansible/roles/web-app-cst-a @ v1 (commit abc)"
PLACED = "web-app-cst-a"


class TestMarker(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.roles = Path(tmp.name) / "roles"
        write(self.roles / PLACED / MARKER_FILE, marker_text(PLACED, PLACED, ORIGIN))
        write(self.roles / "web-app-cst-hand" / "mine.yml", "mine: true\n")
        write(self.roles / "web-app-cst-forged" / MARKER_FILE, "something else\n")
        shutil.copytree(self.roles / PLACED, self.roles / "web-app-cst-copy")
        (self.roles / "web-app-cst-linked" / "x").mkdir(parents=True)
        (self.roles / "web-app-cst-linked" / MARKER_FILE).symlink_to(
            self.roles / PLACED / MARKER_FILE
        )
        write(
            self.roles / "web-app-nextcloud" / MARKER_FILE,
            marker_text("web-app-nextcloud", "web-app-nextcloud", ORIGIN),
        )
        (self.roles / "web-app-cst-link").symlink_to(self.roles / PLACED)

    def test_only_a_directory_whose_marker_names_it_is_placed(self):
        self.assertTrue(is_placed(self.roles / PLACED))
        self.assertFalse(is_placed(self.roles / "web-app-cst-hand"))
        self.assertFalse(is_placed(self.roles / "web-app-cst-forged"))

    def test_a_copy_under_another_name_is_not_placed(self):
        self.assertFalse(is_placed(self.roles / "web-app-cst-copy"))

    def test_a_marker_that_is_a_symbolic_link_is_not_read(self):
        self.assertFalse(is_placed(self.roles / "web-app-cst-linked"))

    def test_a_marker_that_is_a_fifo_is_not_placed(self):
        fifo = self.roles / "web-app-cst-fifo"
        fifo.mkdir()
        os.mkfifo(fifo / MARKER_FILE)
        self.assertFalse(is_placed(fifo))

    def test_a_symbolic_link_to_a_placed_role_is_not_placed(self):
        self.assertFalse(is_placed(self.roles / "web-app-cst-link"))

    def test_provenance_reads_back_what_the_pull_recorded(self):
        self.assertEqual(ORIGIN, provenance(self.roles / PLACED))

    def test_custom_entries_are_every_prefixed_entry(self):
        self.assertEqual(
            [
                PLACED,
                "web-app-cst-copy",
                "web-app-cst-forged",
                "web-app-cst-hand",
                "web-app-cst-link",
                "web-app-cst-linked",
            ],
            [entry.name for entry in custom_entries(self.roles)],
        )

    def test_placed_roles_are_the_custom_entries_whose_marker_names_them(self):
        self.assertEqual([PLACED], [entry.name for entry in placed_roles(self.roles)])


class TestWriteMarker(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.role = self.root / PLACED
        self.role.mkdir()

    def test_marker_names_the_directory_and_the_group(self):
        write_marker(self.role, PLACED, ORIGIN)
        self.assertTrue(is_placed(self.role))
        self.assertEqual(ORIGIN, provenance(self.role))

    def test_a_symbolic_link_under_the_marker_name_is_replaced_not_followed(self):
        victim = write(self.root / "victim.yml", "victim: true\n")
        (self.role / MARKER_FILE).symlink_to(victim)
        write_marker(self.role, PLACED, ORIGIN)
        text = victim.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        self.assertEqual("victim: true\n", text)
        self.assertFalse((self.role / MARKER_FILE).is_symlink())
        self.assertTrue(is_placed(self.role))

    def test_a_directory_under_the_marker_name_is_replaced(self):
        write(self.role / MARKER_FILE / "nested.yml", "nested: true\n")
        write_marker(self.role, PLACED, ORIGIN)
        self.assertTrue((self.role / MARKER_FILE).is_file())
        self.assertTrue(is_placed(self.role))


if __name__ == "__main__":
    unittest.main()
