from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

nav_utils = importlib.import_module("infinito_docs.extensions.nav_utils")


class TestNavUtils(unittest.TestCase):
    def test_natural_sort_orders_numbers_by_value(self) -> None:
        self.assertLess(
            nav_utils.natural_sort_key("file2"), nav_utils.natural_sort_key("file10")
        )

    def test_markdown_headings_skip_fenced_code(self) -> None:
        with TemporaryDirectory() as td:
            page = Path(td) / "x.md"
            page.write_text(
                "# Title\n```\n# Not a heading\n```\n## Sub Page\n", encoding="utf-8"
            )

            headings = nav_utils.extract_headings_from_file(page)

        self.assertEqual(
            [(h["level"], h["text"], h["anchor"]) for h in headings],
            [(1, "Title", "title"), (2, "Sub Page", "sub-page")],
        )

    def test_max_level_drops_deeper_markdown_headings(self) -> None:
        with TemporaryDirectory() as td:
            page = Path(td) / "x.md"
            page.write_text("# One\n## Two\n### Three\n", encoding="utf-8")

            headings = nav_utils.extract_headings_from_file(page, max_level=2)

        self.assertEqual([h["text"] for h in headings], ["One", "Two"])

    def test_rst_heading_needs_an_underline_of_three(self) -> None:
        with TemporaryDirectory() as td:
            page = Path(td) / "x.rst"
            page.write_text("Header\n======\n\nShort\n--\n", encoding="utf-8")

            headings = nav_utils.extract_headings_from_file(page)

        self.assertEqual([h["text"] for h in headings], ["Header"])

    def test_index_without_headings_falls_back_to_readme(self) -> None:
        with TemporaryDirectory() as td:
            (Path(td) / "index.rst").write_text(".. toctree::\n", encoding="utf-8")
            (Path(td) / "README.md").write_text("# Folder\n", encoding="utf-8")

            headings = nav_utils.extract_headings_from_file(Path(td) / "index.rst")

        self.assertEqual([h["text"] for h in headings], ["Folder"])

    def test_group_nests_by_level_and_sort_puts_priority_first(self) -> None:
        headings = [
            {"level": 1, "text": "B", "anchor": "b", "priority": 1, "filename": "b"},
            {"level": 2, "text": "B1", "anchor": "b1", "priority": 1, "filename": "b"},
            {"level": 1, "text": "A", "anchor": "a", "priority": 0, "filename": "z"},
        ]
        tree = nav_utils.group_headings(headings)
        nav_utils.sort_tree(tree)

        self.assertEqual([item["text"] for item in tree], ["A", "B"])
        self.assertEqual([item["text"] for item in tree[1]["children"]], ["B1"])


if __name__ == "__main__":
    unittest.main()
