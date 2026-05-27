import os
import sys
import json
import tempfile
import shutil
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

# Absolute path to the tree/__main__.py script
SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../cli/build/tree/__main__.py")
)

class TestTreeShadowFolder(unittest.TestCase):
    def setUp(self):
        # Create a temporary roles directory and a dummy role
        self.roles_dir = tempfile.mkdtemp()
        self.role_name = "dummyrole"
        self.role_path = os.path.join(self.roles_dir, self.role_name)
        os.makedirs(os.path.join(self.role_path, "meta"))

        # Create a temporary shadow folder
        self.shadow_dir = tempfile.mkdtemp()

        # Patch sys.argv so the script picks up our dirs
        self.orig_argv = sys.argv[:]
        sys.argv = [
            SCRIPT_PATH,
            "-d", self.roles_dir,
            "-s", self.shadow_dir,
            "-o", "json"
        ]

        # Ensure project root is on sys.path so `import cli.build.tree` works
        from . import PROJECT_ROOT

        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))

    def tearDown(self):
        # Restore original argv and clean up
        sys.argv = self.orig_argv
        shutil.rmtree(self.roles_dir)
        shutil.rmtree(self.shadow_dir)

    @staticmethod
    def _sync_as_completed(futures):
        return list(futures)

    @patch("cli.build.tree._main.as_completed", side_effect=_sync_as_completed.__func__)
    @patch("cli.build.tree._main.ProcessPoolExecutor")
    @patch("cli.build.tree.build_mappings")
    @patch("cli.build.tree.output_graph")
    def test_tree_json_written_to_shadow_folder(
        self,
        mock_output_graph,
        mock_build_mappings,
        mock_executor_cls,
        _mock_as_completed,
    ):
        # Prepare the dummy graph that build_mappings should return
        dummy_graph = {"dummy": {"test": 42}}
        mock_build_mappings.return_value = dummy_graph

        class DummyFuture:
            def __init__(self, value=None, exc=None):
                self._value = value
                self._exc = exc

            def result(self):
                if self._exc is not None:
                    raise self._exc
                return self._value

        class DummyExecutor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, fn, *args, **kwargs):
                try:
                    return DummyFuture(fn(*args, **kwargs))
                except Exception as exc:
                    return DummyFuture(exc=exc)

        mock_executor_cls.return_value = DummyExecutor()

        # Import the script module by name (so our @patch applies) and call main()
        import importlib
        tree_mod = importlib.import_module("cli.build.tree")
        with redirect_stdout(StringIO()):
            tree_mod.main()

        # Verify that tree.json was written into the shadow folder
        expected_tree_path = os.path.join(
            self.shadow_dir, self.role_name, "meta", "tree.json"
        )
        self.assertTrue(
            os.path.isfile(expected_tree_path),
            f"tree.json not found at {expected_tree_path}"
        )

        # Verify contents match our dummy_graph
        with open(expected_tree_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data, dummy_graph, "tree.json content mismatch")

        # Ensure that no tree.json was written to the real meta/ folder
        original_tree_path = os.path.join(self.role_path, "meta", "tree.json")
        self.assertFalse(
            os.path.exists(original_tree_path),
            "tree.json should NOT be written to the real meta/ folder"
        )

if __name__ == "__main__":
    unittest.main()
