"""Unit tests for `utils.cache.files`.

Covers the project-tree walk cache, the file-content cache, and the
combined ``iter_project_files_with_content`` helper. All tests run
against a synthetic tempdir; ``PROJECT_ROOT`` is monkey-patched onto
the module so the real repo tree is never touched.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from utils.cache import files as files_module
from utils.cache import gitignore as gitignore_module
from utils.cache.files import (
    _reset,
    is_translation_catalog,
    iter_non_ignored_files,
    iter_project_files,
    iter_project_files_with_content,
    read_text,
)
from utils.roles.mapping import (
    ROLE_FILE_HANDLERS_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TASKS_MAIN,
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

    def test_cached_file_deleted_later_returns_the_cached_text(self) -> None:
        path = _touch(self.root / "a.txt", "first")
        self.assertEqual(read_text(str(path)), "first")
        path.unlink()
        self.assertEqual(read_text(str(path)), "first")

    def test_file_above_the_cache_bound_is_never_cached(self) -> None:
        path = _touch(self.root / "catalog.po", "first")
        with patch.object(files_module, "READ_TEXT_CACHE_MAX_BYTES", 4):
            self.assertEqual(read_text(str(path)), "first")
            path.write_text("second", encoding="utf-8")
            self.assertEqual(read_text(str(path)), "second")
        self.assertEqual(files_module._read_cached.cache_info().currsize, 0)

    def test_file_at_the_cache_bound_stays_cached(self) -> None:
        path = _touch(self.root / "a.txt", "four")
        with patch.object(files_module, "READ_TEXT_CACHE_MAX_BYTES", 4):
            self.assertEqual(read_text(str(path)), "four")
            path.write_text("zero", encoding="utf-8")
            self.assertEqual(read_text(str(path)), "four")


class TestIterProjectFiles(_ProjectRootFixture, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        _touch(self.root / f"roles/web-app-foo/{ROLE_FILE_META_SERVICES}", "foo: 1")
        _touch(self.root / "roles/web-app-foo/templates/x.j2", "{{ x }}")
        _touch(self.root / "docs/readme.md", "# Hi")
        _touch(self.root / "tests/unit/test_a.py", "import unittest")
        _touch(self.root / ".git/HEAD", "ref: refs/heads/main")
        _touch(self.root / "node_modules/pkg/index.js", "module.exports = {};")
        _touch(self.root / "vendor/nette/utils/readme.md", "# vendored")
        _touch(self.root / "__pycache__/dead.pyc", "")
        _touch(self.root / "build/ruff-cache-0/0.16.7/entry.json", "{}")
        _touch(self.root / "cli/build/docs/readme/overview.py", "x = 1")

    def test_skip_dirs_pruned(self) -> None:
        all_paths = set(iter_project_files())
        self.assertFalse(
            any("/.git/" in p for p in all_paths),
            f".git not pruned in {all_paths}",
        )
        self.assertFalse(any("/__pycache__/" in p for p in all_paths))
        self.assertFalse(any("/node_modules/" in p for p in all_paths))
        self.assertFalse(any("/vendor/" in p for p in all_paths))

    def test_build_is_pruned_at_the_root_only(self) -> None:
        all_paths = set(iter_project_files())
        self.assertFalse(
            any(p.startswith(f"{self.root}/build/") for p in all_paths),
            f"root build/ artefacts reached the walk: {all_paths}",
        )
        self.assertTrue(
            any(p.endswith("cli/build/docs/readme/overview.py") for p in all_paths),
            f"cli/build is source and must survive the prune: {all_paths}",
        )

    def test_git_local_exclude_dirs_pruned(self) -> None:
        """Plain directory entries in .git/info/exclude are pruned; file
        patterns and globs are left to git."""
        _touch(
            self.root / ".git/info/exclude",
            "# comment\n/local-tool-out/\nsettings.local.json\n*.tmp\n",
        )
        _touch(self.root / "local-tool-out/report.md", "generated")
        _reset()
        all_paths = set(iter_project_files())
        self.assertFalse(any("/local-tool-out/" in p for p in all_paths))
        self.assertTrue(any(p.endswith("readme.md") for p in all_paths))

    def test_extensions_filter(self) -> None:
        ymls = list(iter_project_files(extensions=(".yml",)))
        self.assertEqual(len(ymls), 1)
        self.assertTrue(ymls[0].endswith("services.yml"))

        markdown = list(iter_project_files(extensions=(".md",)))
        self.assertEqual(len(markdown), 1)
        self.assertTrue(markdown[0].endswith("readme.md"))

    def test_exclude_tests_skips_tests_subtree(self) -> None:
        with_tests = list(iter_project_files(extensions=(".py",)))
        self.assertEqual(len(with_tests), 2)

        without_tests = list(
            iter_project_files(extensions=(".py",), exclude_tests=True)
        )
        self.assertEqual(len(without_tests), 1)
        self.assertTrue(without_tests[0].endswith("cli/build/docs/readme/overview.py"))

    def test_exclude_dirs_path_segment_match(self) -> None:
        kept = list(iter_project_files(exclude_dirs=("docs",)))
        self.assertFalse(any(p.endswith("readme.md") for p in kept))

    def test_walk_is_cached_across_calls(self) -> None:
        first = set(iter_project_files())
        _touch(self.root / "after.txt", "late")
        second = set(iter_project_files())
        self.assertEqual(first, second)

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
        list(iter_project_files())
        read_text(str(self.root / "x.txt"))
        _touch(self.root / "y.txt", "v2")
        (self.root / "x.txt").write_text("v1-changed", encoding="utf-8")
        self.assertNotIn(str(self.root / "y.txt"), set(iter_project_files()))
        self.assertEqual(read_text(str(self.root / "x.txt")), "v1")
        _reset()
        self.assertIn(str(self.root / "y.txt"), set(iter_project_files()))
        self.assertEqual(read_text(str(self.root / "x.txt")), "v1-changed")


class TestNonIgnoredIndex(_ProjectRootFixture, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(gitignore_module._reset)
        _touch(self.root / ".gitignore", "ignored/\n*.log\n")
        for rel in ("kept.txt", "ignored/x.txt", "a.log", "tests/t.py", "docs/d.md"):
            _touch(self.root / rel)

    def _rels(self, **kwargs) -> set[str]:
        return {
            Path(path).relative_to(self.root).as_posix()
            for path in iter_non_ignored_files(**kwargs)
        }

    def test_gitignored_paths_are_left_out_and_the_filters_apply(self) -> None:
        self.assertEqual(
            self._rels(), {".gitignore", "kept.txt", "tests/t.py", "docs/d.md"}
        )
        self.assertEqual(
            self._rels(exclude_tests=True, exclude_dirs=("docs",)),
            {".gitignore", "kept.txt"},
        )
        self.assertEqual(self._rels(extensions=(".py",)), {"tests/t.py"})

    def test_the_gitignore_match_runs_once_for_every_caller(self) -> None:
        with patch.object(
            files_module,
            "is_path_gitignored",
            wraps=files_module.is_path_gitignored,
        ) as matcher:
            self._rels()
            self._rels(exclude_tests=True)
            self._rels(extensions=(".md",))
        self.assertEqual(matcher.call_count, len(list(iter_project_files())))

    def test_the_index_holds_paths_only(self) -> None:
        yielded = tuple(iter_non_ignored_files())
        self.assertEqual(files_module._non_ignored_files.cache_info().currsize, 1)
        cached = files_module._non_ignored_files(
            str(self.root),
            str(self.root),
            gitignore_module.load_gitignore_patterns(str(self.root)),
        )
        self.assertEqual(cached, yielded)
        self.assertTrue(all(isinstance(path, str) for path in cached))

    def test_a_reloaded_gitignore_is_matched_afresh(self) -> None:
        self.assertIn("kept.txt", self._rels())
        _touch(self.root / ".gitignore", "ignored/\n*.log\nkept.txt\n")
        gitignore_module._reset()
        self.assertNotIn("kept.txt", self._rels())


class TestTranslationCatalogs(_ProjectRootFixture, unittest.TestCase):
    CATALOG = "locale/de/LC_MESSAGES/docs.po"

    def setUp(self) -> None:
        super().setUp()
        _touch(self.root / self.CATALOG, 'msgid "x"\n')
        _touch(self.root / "docs/a.md", "doc")

    def test_only_po_files_of_the_locale_tree_are_catalogs(self) -> None:
        self.assertTrue(is_translation_catalog(self.CATALOG))
        for rel in (
            "docs/locale.po",
            "roles/web-app-x/locale/de.po",
            "locale/de/LC_MESSAGES/docs.mo",
            "locales/de/docs.po",
        ):
            with self.subTest(rel=rel):
                self.assertFalse(is_translation_catalog(rel))

    def test_a_content_scan_leaves_the_catalogs_unread(self) -> None:
        with patch.object(
            files_module, "read_text", wraps=files_module.read_text
        ) as reader:
            found = [path for path, _ in iter_project_files_with_content()]
        self.assertEqual(found, [str(self.root / "docs/a.md")])
        self.assertNotIn(
            str(self.root / self.CATALOG), [c.args[0] for c in reader.call_args_list]
        )

    def test_a_scan_that_opts_in_reads_the_catalogs(self) -> None:
        found = dict(iter_project_files_with_content(include_catalogs=True))
        self.assertEqual(found[str(self.root / self.CATALOG)], 'msgid "x"\n')
        self.assertIn(str(self.root / "docs/a.md"), found)

    def test_the_path_walks_keep_listing_the_catalogs(self) -> None:
        self.assertIn(str(self.root / self.CATALOG), set(iter_project_files()))
        self.assertIn(str(self.root / self.CATALOG), set(iter_non_ignored_files()))


class TestRepositoryFiles(_ProjectRootFixture, unittest.TestCase):
    TRACKED = f"roles/web-app-nextcloud/{ROLE_FILE_TASKS_MAIN}"
    CUSTOM = f"roles/web-app-cst-demo/{ROLE_FILE_TASKS_MAIN}"

    def _git(self, *listings: bytes):
        return patch.object(
            files_module.subprocess,
            "run",
            side_effect=[SimpleNamespace(stdout=listing) for listing in listings],
        )

    def test_lists_placed_custom_roles_next_to_the_tracked_files(self) -> None:
        _touch(self.root / self.TRACKED, "- y")
        _touch(self.root / self.CUSTOM, "- x")
        _touch(self.root / "roles/web-app-cst-demo/__pycache__/x.pyc", "")
        with self._git(f"{self.TRACKED}\0".encode(), b"", b""):
            self.assertEqual(
                (self.CUSTOM, self.TRACKED),
                files_module.repository_files(),
            )

    def test_lists_only_the_tracked_files_without_placed_custom_roles(self) -> None:
        _touch(self.root / self.TRACKED, "- y")
        _touch(self.root / "build/install.stamp", "")
        with self._git(f"{self.TRACKED}\0".encode(), b"", b""):
            self.assertEqual((self.TRACKED,), files_module.repository_files())

    def test_leaves_out_a_tracked_file_deleted_in_the_worktree(self) -> None:
        gone = "roles/web-app-nextcloud/filter_plugins/gone.py"
        with self._git(
            f"{self.TRACKED}\0{gone}\0".encode(), f"{gone}\0".encode(), b""
        ) as run:
            self.assertEqual((self.TRACKED,), files_module.repository_files())
        self.assertEqual(["--deleted"], run.call_args_list[1].args[0][-1:])

    def test_default_adds_the_files_gitignore_does_not_exclude(self) -> None:
        with self._git(f"{self.TRACKED}\0".encode(), b"", b"new.py\0") as run:
            self.assertEqual(
                ("new.py", self.TRACKED),
                files_module.repository_files(),
            )
        self.assertEqual(
            ["--others", "--exclude-standard"],
            run.call_args_list[2].args[0][-2:],
        )

    def test_negative_control_tracked_only_leaves_a_new_file_out(self) -> None:
        with self._git(f"{self.TRACKED}\0".encode(), b"") as run:
            self.assertEqual(
                (self.TRACKED,), files_module.repository_files(untracked=False)
            )
        self.assertEqual(len(run.call_args_list), 2)

    def test_a_git_failure_propagates(self) -> None:
        with (
            patch.object(
                files_module.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(128, "git"),
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            files_module.repository_files()


class TestLintScope(unittest.TestCase):
    def _scope(self, value: str):
        return patch.dict(files_module.os.environ, {files_module.LINT_SCOPE_ENV: value})

    def test_unset_scope_keeps_every_path(self) -> None:
        with patch.dict(files_module.os.environ, clear=True):
            self.assertTrue(
                files_module.in_lint_scope(f"roles/a/{ROLE_FILE_TASKS_MAIN}")
            )

    def test_a_role_scope_keeps_its_files_only(self) -> None:
        with self._scope("roles/web-app-a/"):
            self.assertEqual(
                [
                    files_module.in_lint_scope(rel)
                    for rel in (
                        f"roles/web-app-a/{ROLE_FILE_HANDLERS_MAIN}",
                        f"roles/web-app-ab/{ROLE_FILE_HANDLERS_MAIN}",
                        "default.env",
                    )
                ],
                [True, False, False],
            )

    def test_a_file_scope_keeps_that_file(self) -> None:
        with self._scope("default.env Makefile"):
            self.assertEqual(files_module.lint_scope(), ("default.env", "Makefile"))
            self.assertTrue(files_module.in_lint_scope("Makefile"))


class TestWalkIsKeyedOnTheRoot(_ProjectRootFixture, unittest.TestCase):
    def test_a_second_root_is_walked_rather_than_answered_from_the_first(
        self,
    ) -> None:
        _touch(self.root / "first.txt", "a")
        self.assertEqual(
            {str(self.root / "first.txt")},
            set(iter_project_files()),
        )

        with TemporaryDirectory() as other:
            other_root = Path(other)
            _touch(other_root / "second.txt", "b")
            with patch.object(files_module, "PROJECT_ROOT", other_root):
                self.assertEqual(
                    {str(other_root / "second.txt")},
                    set(iter_project_files()),
                    "the walk answered for the previous root, so a test that "
                    "points PROJECT_ROOT at a fixture silently sweeps the real "
                    "repository instead",
                )

        self.assertEqual(
            {str(self.root / "first.txt")},
            set(iter_project_files()),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
