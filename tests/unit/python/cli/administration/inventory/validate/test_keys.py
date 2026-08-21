"""Unit tests for ``cli.administration.inventory.validate.keys``."""

from __future__ import annotations

import unittest

from cli.administration.inventory.validate.keys import recursive_keys


class TestRecursiveKeys(unittest.TestCase):
    def test_empty_dict(self):
        self.assertEqual(recursive_keys({}), set())

    def test_non_dict_returns_empty(self):
        self.assertEqual(recursive_keys(None), set())
        self.assertEqual(recursive_keys("string"), set())
        self.assertEqual(recursive_keys(42), set())
        self.assertEqual(recursive_keys([1, 2, 3]), set())

    def test_flat_keys(self):
        self.assertEqual(
            recursive_keys({"a": 1, "b": 2}),
            {"a", "b"},
        )

    def test_nested_keys_are_dotted(self):
        self.assertEqual(
            recursive_keys({"services": {"port": 8080, "enabled": True}}),
            {"services", "services.port", "services.enabled"},
        )

    def test_deeply_nested(self):
        self.assertEqual(
            recursive_keys({"a": {"b": {"c": 1}}}),
            {"a", "a.b", "a.b.c"},
        )

    def test_prefix_is_applied(self):
        self.assertEqual(
            recursive_keys({"x": 1}, prefix="parent"),
            {"parent.x"},
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
