import os
import tempfile
import unittest
from pathlib import Path

from plugins.filter.invokable_paths import get_invokable_paths
from utils.cache.yaml import dump_yaml


class TestInvokablePaths(unittest.TestCase):
    def write_yaml(self, data):
        fd, path = tempfile.mkstemp(suffix=".yml")
        os.close(fd)
        dump_yaml(path, data)
        return path

    def test_empty_roles(self):
        path = self.write_yaml({})
        self.assertEqual(get_invokable_paths(path), [])
        Path(path).unlink()

    def test_single_invokable_true(self):
        data = {"role1": {"invokable": True}}
        path = self.write_yaml(data)
        self.assertEqual(get_invokable_paths(path), ["role1"])
        Path(path).unlink()

    def test_single_invokable_false_or_missing(self):
        data_false = {"role1": {"invokable": False}}
        path_false = self.write_yaml(data_false)
        self.assertEqual(get_invokable_paths(path_false), [])
        Path(path_false).unlink()

        data_missing = {"role1": {}}
        path_missing = self.write_yaml(data_missing)
        self.assertEqual(get_invokable_paths(path_missing), [])
        Path(path_missing).unlink()

    def test_nested_and_deeply_nested(self):
        data = {
            "parent": {
                "invokable": True,
                "child": {"invokable": True},
                "other": {"invokable": False},
                "sub": {"deep": {"invokable": True}},
            }
        }
        path = self.write_yaml(data)
        expected = ["parent", "parent-child", "parent-sub-deep"]
        self.assertEqual(sorted(get_invokable_paths(path)), sorted(expected))
        Path(path).unlink()

    def test_ignore_metadata_and_unwrap(self):
        data = {
            "roles": {
                "role1": {
                    "invokable": True,
                    "title": {"foo": "bar"},
                    "description": {"bar": "baz"},
                }
            }
        }
        path = self.write_yaml(data)
        self.assertEqual(get_invokable_paths(path), ["role1"])
        Path(path).unlink()

    def test_suffix_appended(self):
        data = {"role1": {"invokable": True}}
        path = self.write_yaml(data)
        self.assertEqual(get_invokable_paths(path, suffix="_suf"), ["role1_suf"])
        Path(path).unlink()


if __name__ == "__main__":
    unittest.main()
