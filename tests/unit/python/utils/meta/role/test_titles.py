from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.meta.role.names import role_names
from utils.meta.role.titles import role_title, role_titles
from utils.roles.mapping import ROLE_FILE_META_MAIN


class TestRoleTitle(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="infinito-titles-")
        self.role = Path(self._tmp.name) / "web-app-demo"
        (self.role / "meta").mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)

    def test_the_readme_heading_is_the_title(self) -> None:
        (self.role / "README.md").write_text("# Demo App\n\nText.\n", encoding="utf-8")

        self.assertEqual(role_title(self.role), "Demo App")

    def test_the_metadata_name_stands_in_without_a_heading(self) -> None:
        (self.role / ROLE_FILE_META_MAIN).write_text(
            "galaxy_info:\n  name: Declared Name\n", encoding="utf-8"
        )

        self.assertEqual(role_title(self.role), "Declared Name")

    def test_the_heading_wins_over_the_metadata(self) -> None:
        (self.role / "README.md").write_text("# Demo App\n", encoding="utf-8")
        (self.role / ROLE_FILE_META_MAIN).write_text(
            "galaxy_info:\n  name: Declared Name\n", encoding="utf-8"
        )

        self.assertEqual(
            role_title(self.role),
            "Demo App",
            "the documentation is built from the heading, so that is what a "
            "reader sees the role called",
        )

    def test_only_the_first_heading_counts(self) -> None:
        (self.role / "README.md").write_text(
            "# Demo App\n\n# Later Heading\n", encoding="utf-8"
        )

        self.assertEqual(role_title(self.role), "Demo App")

    def test_a_role_declaring_nothing_has_no_title(self) -> None:
        self.assertEqual(role_title(self.role), "")


class TestRepositorySources(unittest.TestCase):
    def test_every_role_directory_is_listed(self) -> None:
        names = role_names()

        self.assertIn("web-app-nextcloud", names)
        self.assertEqual(list(names), sorted(names))

    def test_the_titles_are_unique_and_sorted(self) -> None:
        titles = role_titles()

        self.assertIn("Nextcloud", titles)
        self.assertEqual(len(titles), len(set(titles)))
        self.assertEqual(list(titles), sorted(titles))


if __name__ == "__main__":
    unittest.main()
