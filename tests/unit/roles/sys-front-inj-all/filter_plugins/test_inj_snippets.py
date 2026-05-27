"""
Unit tests for roles/sys-front-inj-all/filter_plugins/inj_snippets.py

- Uses tempfile.TemporaryDirectory for an isolated roles/ tree.
- Loads inj_snippets.py by absolute path (no sys.path issues).
- Monkey-patches inj_snippets._ROLES_DIR to the temp roles/ path.
- Calls the filter function via the loaded module to avoid method-binding.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path


class TestInjSnippets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Find repo root by locating inj_snippets.py upwards from this file
        cls.test_dir = str(Path(__file__).parent)
        root = cls.test_dir
        inj_rel = str(
            Path("roles") / "sys-front-inj-all" / "filter_plugins" / "inj_snippets.py"
        )

        while True:
            candidate = str(Path(root) / inj_rel)
            if Path(candidate).is_file():
                cls.repo_root = root
                cls.inj_snippets_path = candidate
                break
            parent = str(Path(root).parent)
            if parent == root:
                raise RuntimeError(f"Could not locate {inj_rel} above {cls.test_dir}")
            root = parent

        # Create isolated temporary roles tree
        cls.tmp = tempfile.TemporaryDirectory(prefix="inj-snippets-test-")
        cls.roles_dir = str(Path(cls.tmp.name) / "roles")
        Path(cls.roles_dir).mkdir(parents=True, exist_ok=True)

        # Dynamically load inj_snippets by file path
        spec = importlib.util.spec_from_file_location(
            "inj_snippets", cls.inj_snippets_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Failed to create import spec for inj_snippets.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Point the module to our temp roles/ directory
        module._ROLES_DIR = cls.roles_dir

        # Keep the loaded module for calls
        cls.mod = module

        # Mock feature names
        cls.feature_head_only = "zz_headonly"
        cls.feature_body_only = "zz_bodyonly"
        cls.feature_both = "zz_both"
        cls.feature_missing = "zz_missing"

        # Create mock roles and snippet files
        cls._mkrole(cls.feature_head_only, head=True, body=False)
        cls._mkrole(cls.feature_body_only, head=False, body=True)
        cls._mkrole(cls.feature_both, head=True, body=True)

    @classmethod
    def _mkrole(cls, feature, head=False, body=False):
        role_dir = str(Path(cls.roles_dir) / f"sys-front-inj-{feature}")
        tmpl_dir = str(Path(role_dir) / "templates")
        Path(tmpl_dir).mkdir(parents=True, exist_ok=True)
        if head:
            with Path(str(Path(tmpl_dir) / "head_sub.j2")).open(
                "w", encoding="utf-8"
            ) as f:
                f.write("<!-- head test -->\n")
        if body:
            with Path(str(Path(tmpl_dir) / "body_sub.j2")).open(
                "w", encoding="utf-8"
            ) as f:
                f.write("<!-- body test -->\n")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_head_features_filter(self):
        features = [self.feature_head_only, self.feature_both, self.feature_body_only]
        result = self.mod.inj_features_filter(features, kind="head")
        self.assertEqual(result, [self.feature_head_only, self.feature_both])

    def test_body_features_filter(self):
        features = [self.feature_head_only, self.feature_both, self.feature_body_only]
        result = self.mod.inj_features_filter(features, kind="body")
        self.assertEqual(result, [self.feature_both, self.feature_body_only])

    def test_raises_when_role_dir_missing(self):
        with self.assertRaises(FileNotFoundError):
            self.mod.inj_features_filter([self.feature_missing], kind="head")
        with self.assertRaises(FileNotFoundError):
            self.mod.inj_features_filter([self.feature_missing], kind="body")

    def test_non_list_input_returns_empty(self):
        self.assertEqual(self.mod.inj_features_filter("not-a-list", kind="head"), [])
        self.assertEqual(self.mod.inj_features_filter(None, kind="body"), [])


if __name__ == "__main__":
    unittest.main()
