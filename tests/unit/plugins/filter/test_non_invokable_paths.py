import os
import tempfile
import unittest
from pathlib import Path

from plugins.filter.invokable_paths import get_non_invokable_paths
from utils.cache.yaml import dump_yaml


class TestNonInvokablePaths(unittest.TestCase):
    def write_yaml(self, data):
        fd, path = tempfile.mkstemp(suffix=".yml")
        os.close(fd)
        dump_yaml(path, data)
        return path

    def test_empty_roles(self):
        path = self.write_yaml({})
        # No roles, so no non-invokable paths
        self.assertEqual(get_non_invokable_paths(path), [])
        Path(path).unlink()

    def test_single_non_invokable_false_and_missing(self):
        data_false = {"role1": {"invokable": False}}
        path_false = self.write_yaml(data_false)
        self.assertEqual(get_non_invokable_paths(path_false), ["role1"])
        Path(path_false).unlink()

        data_missing = {"role1": {}}
        path_missing = self.write_yaml(data_missing)
        self.assertEqual(get_non_invokable_paths(path_missing), ["role1"])
        Path(path_missing).unlink()

    def test_single_invokable_true_excluded(self):
        data = {"role1": {"invokable": True}}
        path = self.write_yaml(data)
        # invokable True should not appear in non-invokable list
        self.assertEqual(get_non_invokable_paths(path), [])
        Path(path).unlink()

    def test_nested_and_deeply_nested(self):
        data = {
            "parent": {
                "invokable": True,
                "child": {"invokable": False},
                "other": {"invokable": True},
                "sub": {"deep": {}},
            }
        }
        path = self.write_yaml(data)
        # 'parent-child' (explicit False), 'parent-sub' (missing invokable), and 'parent-sub-deep' (missing) are non-invokable
        expected = ["parent-child", "parent-sub", "parent-sub-deep"]
        self.assertEqual(sorted(get_non_invokable_paths(path)), sorted(expected))
        Path(path).unlink()

    def test_unwrap_roles_key(self):
        data = {"roles": {"role1": {"invokable": False}, "role2": {"invokable": True}}}
        path = self.write_yaml(data)
        # Only role1 is non-invokable
        self.assertEqual(get_non_invokable_paths(path), ["role1"])
        Path(path).unlink()

    def test_suffix_appended(self):
        data = {"role1": {"invokable": False}}
        path = self.write_yaml(data)
        self.assertEqual(get_non_invokable_paths(path, suffix="_suf"), ["role1_suf"])
        Path(path).unlink()


if __name__ == "__main__":
    unittest.main()
