import shutil
import tempfile
import unittest
from pathlib import Path

from cli.build import tree
from utils.roles.mapping import ROLE_FILE_META_MAIN


class TestTreeMain(unittest.TestCase):
    def setUp(self):
        # Create a temporary roles directory with a fake role
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

    def test_main_execution_does_not_raise(self):
        # Mocking sys.argv and running main should not raise
        import sys

        old_argv = sys.argv
        sys.argv = ["tree/__main__.py", "-d", self.temp_dir, "-p"]
        try:
            tree.main()
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    unittest.main()
