"""The enumeration both markdown lints scan must not quietly come back empty.

Each lint reports only what it finds, so an enumeration that yields nothing
makes both of them pass while checking nothing. That is the one way this
helper can fail without anything turning red, so it is pinned here.
"""

from __future__ import annotations

import unittest

from . import AGENT_STATE, PROJECT_ROOT, markdown_files

FLOOR = 100


class TestMarkdownFiles(unittest.TestCase):
    def setUp(self) -> None:
        self.files = markdown_files()

    def test_the_repository_yields_a_plausible_number_of_pages(self) -> None:
        self.assertGreater(
            len(self.files),
            FLOOR,
            f"only {len(self.files)} markdown files were enumerated. Both "
            "markdown lints scan this list, so a short one makes them pass "
            "without checking anything.",
        )

    def test_every_entry_exists_and_is_markdown(self) -> None:
        missing = [path for path in self.files if not path.is_file()]
        foreign = [path for path in self.files if path.suffix != ".md"]

        self.assertEqual(missing, [], "enumerated paths that are not files")
        self.assertEqual(foreign, [], "enumerated paths that are not markdown")

    def test_ignored_trees_stay_out(self) -> None:
        excluded = {".git", "node_modules", "venv", "__pycache__", *AGENT_STATE}
        inside = [
            path
            for path in self.files
            if excluded & set(path.relative_to(PROJECT_ROOT).parts)
        ]

        self.assertEqual(inside, [], "files from an ignored tree were enumerated")


if __name__ == "__main__":
    unittest.main()
