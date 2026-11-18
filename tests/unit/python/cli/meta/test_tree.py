import contextlib
import io
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from cli.build import tree
from utils.roles.mapping import ROLE_FILE_META_MAIN


class TestTreeMain(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.role_name = "testrole"
        self.role_path = str(Path(self.temp_dir) / self.role_name)
        Path(str(Path(self.role_path) / "meta")).mkdir(parents=True)

        meta_path = str(Path(self.role_path) / ROLE_FILE_META_MAIN)
        with Path(meta_path).open("w") as f:
            f.write("galaxy_info:\n  author: test\n  run_after: []\ndependencies: []\n")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_find_roles(self):
        roles = list(tree.find_roles(self.temp_dir))
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0][0], self.role_name)

    def test_main_preview_prints_the_graphs_and_writes_no_tree_file(self):
        out = io.StringIO()
        with (
            unittest.mock.patch.object(
                sys, "argv", ["tree/__main__.py", "-d", self.temp_dir, "-p"]
            ),
            contextlib.redirect_stdout(out),
        ):
            tree.main()
        self.assertIn(f"--- {self.role_name}_", out.getvalue())
        self.assertFalse((Path(self.role_path) / "meta" / "tree.json").exists())


if __name__ == "__main__":
    unittest.main()
