"""Unit tests for `utils.cache.files`.

Covers the project-tree walk cache, the file-content cache, and the
combined ``iter_project_files_with_content`` helper. All tests run
against a synthetic tempdir; ``PROJECT_ROOT`` is monkey-patched onto
the module so the real repo tree is never touched.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.cache import files as files_module
from utils.cache.files import (
    _reset,
    iter_project_files,
    iter_project_files_with_content,
    read_text,
)


def _touch(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class _ProjectRootFixture:
    """Mixin that sets up a synthetic PROJECT_ROOT for every test in the
    subclass. Combined with ``unittest.TestCase`` via multiple inheritance
    so the lint guard ``test_all_test_files_have_tests`` can see the
    ``TestCase`` base directly on the concrete test classes.
    """

    def setUp(self) -> None:
        super().setUp()
        _reset()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self._patcher = patch.object(files_module, "PROJECT_ROOT", self.root)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(_reset)


class TestReadText(_ProjectRootFixture, unittest.TestCase):
    def test_returns_utf8_content(self) -> None:
        path = _touch(self.root / "a.txt", "héllo")
        self.assertEqual(read_text(str(path)), "héllo")

    def test_second_call_hits_cache(self) -> None:
        path = _touch(self.root / "a.txt", "first")
        self.assertEqual(read_text(str(path)), "first")
        path.write_text("changed", encoding="utf-8")
        # Same string path → cache hit; the on-disk change is not seen.
        self.assertEqual(read_text(str(path)), "first")

    def test_reset_invalidates_cache(self) -> None:
        path = _touch(self.root / "a.txt", "first")
        self.assertEqual(read_text(str(path)), "first")
        path.write_text("second", encoding="utf-8")
        _reset()
        self.assertEqual(read_text(str(path)), "second")

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            read_text(str(self.root / "nope.txt"))


class TestIterProjectFiles(_ProjectRootFixture, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        # Build a small synthetic tree.
        _touch(self.root / "roles/web-app-foo/meta/services.yml", "foo: 1")
        _touch(self.root / "roles/web-app-foo/templates/x.j2", "{{ x }}")
        _touch(self.root / "docs/readme.md", "# Hi")
        _touch(self.root / "tests/unit/test_a.py", "import unittest")
        _touch(self.root / ".git/HEAD", "ref: refs/heads/main")
        _touch(self.root / "node_modules/pkg/index.js", "module.exports = {};")
        _touch(self.root / "__pycache__/dead.pyc", "")

    def test_skip_dirs_pruned(self) -> None:
        all_paths = set(iter_project_files())
        # The pruned dirs MUST never appear in the walk.
        self.assertFalse(
            any("/.git/" in p for p in all_paths),
            f".git not pruned in {all_paths}",
        )
        self.assertFalse(any("/__pycache__/" in p for p in all_paths))
        self.assertFalse(any("/node_modules/" in p for p in all_paths))

    def test_extensions_filter(self) -> None:
        ymls = list(iter_project_files(extensions=(".yml",)))
        self.assertEqual(len(ymls), 1)
        self.assertTrue(ymls[0].endswith("services.yml"))

        markdown = list(iter_project_files(extensions=(".md",)))
        self.assertEqual(len(markdown), 1)
        self.assertTrue(markdown[0].endswith("readme.md"))

    def test_exclude_tests_skips_tests_subtree(self) -> None:
        with_tests = list(iter_project_files(extensions=(".py",)))
        self.assertEqual(len(with_tests), 1)

        without_tests = list(
            iter_project_files(extensions=(".py",), exclude_tests=True)
        )
        self.assertEqual(without_tests, [])

    def test_exclude_dirs_path_segment_match(self) -> None:
        # Excluding "docs" must drop the markdown file under docs/.
        kept = list(iter_project_files(exclude_dirs=("docs",)))
        self.assertFalse(any(p.endswith("readme.md") for p in kept))

    def test_walk_is_cached_across_calls(self) -> None:
        # First call populates the cache, then we add a new file: a fresh
        # walk would discover it; the cache MUST not.
        first = set(iter_project_files())
        _touch(self.root / "after.txt", "late")
        second = set(iter_project_files())
        self.assertEqual(first, second)

        # _reset() clears the cache → the new file is now visible.
        _reset()
        third = set(iter_project_files())
        self.assertIn(str(self.root / "after.txt"), third)


class TestIterProjectFilesWithContent(_ProjectRootFixture, unittest.TestCase):
    def test_yields_path_and_content(self) -> None:
        _touch(self.root / "a.txt", "alpha")
        _touch(self.root / "b.txt", "beta")
        result = sorted(iter_project_files_with_content(extensions=(".txt",)))
        self.assertEqual(
            result,
            sorted(
                [
                    (str(self.root / "a.txt"), "alpha"),
                    (str(self.root / "b.txt"), "beta"),
                ]
            ),
        )

    def test_non_utf8_files_silently_skipped(self) -> None:
        good = self.root / "good.bin"
        bad = self.root / "bad.bin"
        good.write_text("ok", encoding="utf-8")
        bad.write_bytes(b"\xff\xfe\x00invalid")
        result = list(iter_project_files_with_content(extensions=(".bin",)))
        self.assertEqual(result, [(str(good), "ok")])


class TestReset(_ProjectRootFixture, unittest.TestCase):
    def test_reset_clears_both_caches(self) -> None:
        _touch(self.root / "x.txt", "v1")
        list(iter_project_files())  # populate walk cache
        read_text(str(self.root / "x.txt"))  # populate text cache
        # Mutate underlying state.
        _touch(self.root / "y.txt", "v2")
        (self.root / "x.txt").write_text("v1-changed", encoding="utf-8")
        # Cached views still see the OLD state.
        self.assertNotIn(str(self.root / "y.txt"), set(iter_project_files()))
        self.assertEqual(read_text(str(self.root / "x.txt")), "v1")
        # Reset → fresh views.
        _reset()
        self.assertIn(str(self.root / "y.txt"), set(iter_project_files()))
        self.assertEqual(read_text(str(self.root / "x.txt")), "v1-changed")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
