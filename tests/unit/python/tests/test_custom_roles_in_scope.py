"""Repository scans read the files of a placed custom role, which Git ignores."""

from __future__ import annotations

import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from tests.lint.filesystem.playwright import test_json_env_key_suffix as json_suffix
from tests.lint.filesystem.playwright import (
    test_unguarded_env_default as unguarded,
)
from tests.lint.repository.documentation import test_markdown_links as links
from tests.lint.repository.structure import test_folder_item_limit as folders
from utils.cache import files as files_module
from utils.roles.mapping import ROLE_FILE_PLAYWRIGHT_SPEC

TRACKED_SPEC = f"roles/web-app-nextcloud/{ROLE_FILE_PLAYWRIGHT_SPEC}"
CUSTOM_SPEC = f"roles/web-app-cst-demo/{ROLE_FILE_PLAYWRIGHT_SPEC}"
UNTRACKED = "roles/web-app-nextcloud/files/playwright/generated.js"


class _CustomRoleFixture:
    """Mixin with a project root holding a tracked role and a placed custom role.

    Combined with ``unittest.TestCase`` on each concrete class so the
    test-discovery lint sees the ``TestCase`` base directly.
    """

    def setUp(self) -> None:
        super().setUp()
        files_module._reset()
        links._tracked_files.cache_clear()
        self.addCleanup(files_module._reset)
        self.addCleanup(links._tracked_files.cache_clear)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for rel in (TRACKED_SPEC, CUSTOM_SPEC, UNTRACKED):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        for module in (files_module, json_suffix, unguarded, links):
            patcher = mock.patch.object(module, "PROJECT_ROOT", self.root)
            patcher.start()
            self.addCleanup(patcher.stop)
        git = mock.patch.object(
            files_module.subprocess, "run", side_effect=self._git_listing
        )
        git.start()
        self.addCleanup(git.stop)

    @staticmethod
    def _git_listing(args, **_kwargs):
        if "--deleted" in args or "--others" in args:
            return SimpleNamespace(stdout=b"")
        return SimpleNamespace(stdout=f"{TRACKED_SPEC}\0".encode())


class TestPlaywrightScansReadCustomRoles(_CustomRoleFixture, unittest.TestCase):
    def test_json_env_key_suffix_scans_a_custom_role_spec(self) -> None:
        self.assertIn(self.root / CUSTOM_SPEC, json_suffix._scan_targets())

    def test_unguarded_env_default_scans_a_custom_role_spec(self) -> None:
        self.assertIn(self.root / CUSTOM_SPEC, unguarded._scan_targets())

    def test_scans_still_skip_an_untracked_file_outside_custom_roles(self) -> None:
        for scan in (json_suffix._scan_targets, unguarded._scan_targets):
            with self.subTest(scan=scan.__module__):
                self.assertNotIn(self.root / UNTRACKED, scan())


class TestMarkdownLinksResolveIntoCustomRoles(_CustomRoleFixture, unittest.TestCase):
    def test_a_link_to_a_custom_role_file_resolves(self) -> None:
        self.assertEqual(
            "", links._unresolvable(self.root / CUSTOM_SPEC, self.root / TRACKED_SPEC)
        )

    def test_a_link_to_an_untracked_file_stays_broken(self) -> None:
        self.assertIn(
            "untracked",
            links._unresolvable(self.root / UNTRACKED, self.root / TRACKED_SPEC),
        )


class TestFolderItemLimitCountsCustomRoles(_CustomRoleFixture, unittest.TestCase):
    def test_a_custom_role_file_is_counted(self) -> None:
        self.assertIn(self.root / CUSTOM_SPEC, folders._tracked_paths(self.root))


if __name__ == "__main__":
    unittest.main()
