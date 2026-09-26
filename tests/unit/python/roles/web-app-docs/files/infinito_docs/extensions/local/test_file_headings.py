from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

local_file_headings = importlib.import_module(
    "infinito_docs.extensions.local.file_headings"
)


def _flatten(items):
    for item in items:
        yield item
        yield from _flatten(item.get("children", []))


class TestLocalFileHeadings(unittest.TestCase):
    def test_collects_the_headings_of_the_page_directory(self) -> None:
        with TemporaryDirectory() as td:
            docs = Path(td) / "docs"
            docs.mkdir()
            (docs / "index.rst").write_text("Index\n=====\n", encoding="utf-8")
            (docs / "readme.md").write_text("# Readme\n", encoding="utf-8")
            (docs / "a.md").write_text("# A\n## A1\n", encoding="utf-8")
            context = {}

            local_file_headings.add_local_file_headings(
                SimpleNamespace(srcdir=td), "docs/index", "page.html", context, None
            )

        items = {item["text"]: item for item in _flatten(context["local_md_headings"])}
        self.assertEqual(set(items), {"Index", "A", "A1"})
        self.assertEqual(items["A1"]["link"], "docs/a")
        self.assertEqual(items["A1"]["anchor"], "a1")
        self.assertEqual(context["local_md_headings"][0]["text"], "Index")

    def test_top_level_page_links_without_a_directory_prefix(self) -> None:
        with TemporaryDirectory() as td:
            (Path(td) / "guide.md").write_text("# Guide\n", encoding="utf-8")
            context = {}

            local_file_headings.add_local_file_headings(
                SimpleNamespace(srcdir=td), "guide", "page.html", context, None
            )

        self.assertEqual(context["local_md_headings"][0]["link"], "guide")

    def test_missing_page_directory_yields_no_headings(self) -> None:
        with TemporaryDirectory() as td:
            context = {}

            local_file_headings.add_local_file_headings(
                SimpleNamespace(srcdir=td), "gone/index", "page.html", context, None
            )

        self.assertEqual(context["local_md_headings"], [])


if __name__ == "__main__":
    unittest.main()
