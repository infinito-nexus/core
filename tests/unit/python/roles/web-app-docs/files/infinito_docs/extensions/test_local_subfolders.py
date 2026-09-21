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

local_subfolders = importlib.import_module("infinito_docs.extensions.local_subfolders")


def _tree(root: Path) -> None:
    (root / "index.rst").write_text("Root\n====\n", encoding="utf-8")
    (root / "a.md").write_text("# A\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "readme.md").write_text("# Sub\n", encoding="utf-8")
    (root / "sub" / "x.rst").write_text("X\n===\n", encoding="utf-8")
    (root / "untitled").mkdir()
    (root / "untitled" / "loose.md").write_text("# Loose\n", encoding="utf-8")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "index.rst").write_text("Hidden\n======\n", encoding="utf-8")


class TestLocalSubfolders(unittest.TestCase):
    def test_tree_titles_folders_by_their_representative_file(self) -> None:
        with TemporaryDirectory() as td:
            _tree(Path(td))

            tree = local_subfolders.collect_folder_tree(td, "")

        self.assertEqual((tree["text"], tree["link"]), ("Root", "index"))
        self.assertEqual(
            [(child["text"], child["link"]) for child in tree["children"]],
            [("A", "a"), ("Sub", "sub/readme")],
        )
        self.assertEqual(
            [
                (child["text"], child["link"])
                for child in tree["children"][1]["children"]
            ],
            [("X", "sub/x")],
        )

    def test_folder_without_representative_file_is_skipped(self) -> None:
        with TemporaryDirectory() as td:
            (Path(td) / "a.md").write_text("# A\n", encoding="utf-8")

            self.assertIsNone(local_subfolders.collect_folder_tree(td, ""))

    def test_mark_current_propagates_to_ancestors_only(self) -> None:
        node = {
            "link": "index",
            "children": [
                {"link": "child/index", "children": []},
                {"link": "other", "children": []},
            ],
        }

        local_subfolders.mark_current(node, "child/index")

        self.assertEqual(
            [
                node["current"],
                node["children"][0]["current"],
                node["children"][1]["current"],
            ],
            [True, True, False],
        )

    def test_page_context_receives_the_marked_tree(self) -> None:
        with TemporaryDirectory() as td:
            _tree(Path(td))
            context = {}

            local_subfolders.add_local_subfolders(
                SimpleNamespace(srcdir=td), "sub/x", "page.html", context, None
            )

        (root,) = context["local_subfolders"]
        self.assertTrue(root["current"])
        self.assertTrue(root["children"][1]["children"][0]["current"])
        self.assertFalse(root["children"][0]["current"])

    def test_tree_is_walked_once_and_pages_keep_their_own_flags(self) -> None:
        with TemporaryDirectory() as td:
            _tree(Path(td))
            app = SimpleNamespace(srcdir=td)
            first, second = {}, {}
            before = local_subfolders._source_tree.cache_info()

            local_subfolders.add_local_subfolders(
                app, "sub/x", "page.html", first, None
            )
            local_subfolders.add_local_subfolders(app, "a", "page.html", second, None)

            after = local_subfolders._source_tree.cache_info()

        self.assertEqual(
            (after.misses - before.misses, after.hits - before.hits), (1, 1)
        )
        self.assertTrue(first["local_subfolders"][0]["children"][1]["current"])
        self.assertFalse(second["local_subfolders"][0]["children"][1]["current"])
        self.assertTrue(second["local_subfolders"][0]["children"][0]["current"])


if __name__ == "__main__":
    unittest.main()
