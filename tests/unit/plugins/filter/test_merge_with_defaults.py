import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(
            str(Path(str(Path(__file__).parent)) / "../../../../plugins/filter")
        ).resolve()
    ),
)

from merge.with_defaults import merge_with_defaults


class TestMergeWithDefaultsFilter(unittest.TestCase):
    def test_basic_merge(self):
        defaults = {
            "app1": {
                "compose": {
                    "network": "default",
                    "services": {"foo": "bar"},
                    "volumes": {"data": "/mnt"},
                },
                "features": {"ldap": True, "sso": False},
                "version": 1,
            }
        }

        customs = {
            "app1": {"compose": {"network": "customnet"}, "version": 2},
            "app2": {"compose": {"network": "other"}},
        }

        expected = {
            "app1": {
                "compose": {
                    "network": "customnet",
                    "services": {"foo": "bar"},
                    "volumes": {"data": "/mnt"},
                },
                "features": {"ldap": True, "sso": False},
                "version": 2,
            },
            "app2": {"compose": {"network": "other"}},
        }

        result = merge_with_defaults(defaults, customs)
        self.assertEqual(result, expected)

    def test_keys_from_defaults_only(self):
        defaults = {
            "foo": {"compose": {"a": 1, "b": 2}, "features": {"x": True}},
        }
        customs = {
            "foo": {},
        }
        expected = {"foo": {"compose": {"a": 1, "b": 2}, "features": {"x": True}}}
        result = merge_with_defaults(defaults, customs)
        self.assertEqual(result, expected)

    def test_custom_overrides_nested_dict(self):
        defaults = {"x": {"compose": {"bar": 1, "baz": 2}}}
        customs = {"x": {"compose": {"bar": 99}}}
        expected = {"x": {"compose": {"bar": 99, "baz": 2}}}
        result = merge_with_defaults(defaults, customs)
        self.assertEqual(result, expected)

    def test_only_defaults_present(self):
        defaults = {"only": {"value": 1}}
        customs = {}
        expected = {"only": {"value": 1}}
        result = merge_with_defaults(defaults, customs)
        self.assertEqual(result, expected)

    def test_only_customs_present(self):
        defaults = {}
        customs = {"x": {"foo": 42}}
        expected = {"x": {"foo": 42}}
        result = merge_with_defaults(defaults, customs)
        self.assertEqual(result, expected)

    def test_deep_merge_multiple_levels(self):
        defaults = {
            "a": {"outer": {"mid": {"inner": 1, "keep": True}}, "plain": "test"}
        }
        customs = {"a": {"outer": {"mid": {"inner": 99}}, "plain": "changed"}}
        expected = {
            "a": {"outer": {"mid": {"inner": 99, "keep": True}}, "plain": "changed"}
        }
        result = merge_with_defaults(defaults, customs)
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
