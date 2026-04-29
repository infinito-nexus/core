"""Unit tests for `utils.cache.yaml` (in-process cached YAML loader)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.cache.yaml import (
    _reset_cache_for_tests,
    dump_yaml,
    invalidate,
    load_yaml,
    load_yaml_any,
)


class TestLoadYaml(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _write(self, name: str, content: str) -> Path:
        path = self.tmp / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_returns_parsed_mapping(self):
        path = self._write("a.yml", "foo: 1\nbar: [x, y]\n")
        result = load_yaml(path)
        self.assertEqual(result, {"foo": 1, "bar": ["x", "y"]})

    def test_second_call_returns_same_instance(self):
        path = self._write("a.yml", "foo: 1\n")
        first = load_yaml(path)
        second = load_yaml(path)
        # Same instance proves the cache hit (not just structural equal).
        self.assertIs(first, second)

    def test_resolved_paths_share_cache_entry(self):
        # Two different spellings of the same absolute path MUST hit the
        # same cache entry. We use "./<name>" vs the bare name from the
        # tmp dir as the second spelling.
        path = self._write("a.yml", "foo: 1\n")
        first = load_yaml(path)
        sibling = path.parent / ("./" + path.name)
        second = load_yaml(sibling)
        self.assertIs(first, second)

    def test_empty_file_returns_empty_dict(self):
        path = self._write("empty.yml", "")
        result = load_yaml(path)
        self.assertEqual(result, {})

    def test_non_mapping_root_raises_value_error(self):
        path = self._write("list.yml", "- 1\n- 2\n")
        with self.assertRaisesRegex(ValueError, "mapping at top-level"):
            load_yaml(path)

    def test_missing_file_raises_by_default(self):
        with self.assertRaises(FileNotFoundError):
            load_yaml(self.tmp / "missing.yml")

    def test_missing_file_returns_default_when_provided(self):
        result = load_yaml(self.tmp / "missing.yml", default_if_missing={})
        self.assertEqual(result, {})

    def test_missing_file_default_is_not_cached(self):
        # If the file appears later, the next read MUST see it instead
        # of the synthetic default.
        path = self.tmp / "appears.yml"
        first = load_yaml(path, default_if_missing={"placeholder": True})
        self.assertEqual(first, {"placeholder": True})
        path.write_text("real: yes\n", encoding="utf-8")
        second = load_yaml(path)
        self.assertEqual(second, {"real": True})


class TestLoadYamlAny(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _write(self, name: str, content: str) -> Path:
        path = self.tmp / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_list_root_returned_unchanged(self):
        path = self._write("tasks.yml", "- name: a\n  debug:\n    msg: hi\n")
        result = load_yaml_any(path)
        self.assertEqual(result, [{"name": "a", "debug": {"msg": "hi"}}])

    def test_dict_root_returned_unchanged(self):
        path = self._write("config.yml", "foo: 1\n")
        self.assertEqual(load_yaml_any(path), {"foo": 1})

    def test_empty_file_returns_empty_dict(self):
        path = self._write("empty.yml", "")
        self.assertEqual(load_yaml_any(path), {})

    def test_load_yaml_any_and_load_yaml_share_cache(self):
        # The two entry points MUST hit the same cache so a hot path
        # that mixes them does not pay the parse cost twice.
        path = self._write("config.yml", "foo: 1\n")
        first = load_yaml_any(path)
        second = load_yaml(path)
        self.assertIs(first, second)

    def test_load_yaml_strict_rejects_list_root(self):
        path = self._write("tasks.yml", "- a\n- b\n")
        with self.assertRaisesRegex(ValueError, "mapping at top-level"):
            load_yaml(path)


class TestDumpYaml(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_dump_writes_file(self):
        path = self.tmp / "out.yml"
        dump_yaml(path, {"a": 1, "b": [2, 3]})
        self.assertEqual(load_yaml(path), {"a": 1, "b": [2, 3]})

    def test_dump_creates_parent_dirs(self):
        path = self.tmp / "deep" / "nested" / "out.yml"
        dump_yaml(path, {"k": "v"})
        self.assertTrue(path.exists())

    def test_dump_evicts_cached_entry(self):
        path = self.tmp / "x.yml"
        path.write_text("v: 1\n", encoding="utf-8")
        cached = load_yaml(path)
        self.assertEqual(cached["v"], 1)
        # External writer would normally bypass the cache; dump_yaml
        # MUST clear the entry so the next read sees the new content.
        dump_yaml(path, {"v": 2})
        refreshed = load_yaml(path)
        self.assertEqual(refreshed["v"], 2)
        self.assertIsNot(cached, refreshed)


class TestInvalidate(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_invalidate_drops_entry(self):
        path = self.tmp / "x.yml"
        path.write_text("v: 1\n", encoding="utf-8")
        first = load_yaml(path)
        # Simulate an external rewrite then explicit invalidation.
        path.write_text("v: 2\n", encoding="utf-8")
        invalidate(path)
        second = load_yaml(path)
        self.assertEqual(second["v"], 2)
        self.assertIsNot(first, second)

    def test_invalidate_unknown_path_is_noop(self):
        # Nothing in the cache for this path, so the call must not raise.
        invalidate(self.tmp / "never-loaded.yml")


if __name__ == "__main__":
    unittest.main()
