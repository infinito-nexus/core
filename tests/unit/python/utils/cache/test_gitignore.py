from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache import gitignore
from utils.roles.custom import ROLES_GLOB
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN


class TestLoadGitignorePatterns(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(gitignore._reset)
        self.root = Path(tmp.name)
        (self.root / ".gitignore").write_text(
            f"# comment\n*.log\n{ROLES_GLOB}\n!keep.log\nbuild/*\n", encoding="utf-8"
        )

    def test_reads_plain_patterns(self):
        patterns = gitignore.load_gitignore_patterns(str(self.root))
        self.assertEqual(("*.log", "build/*"), patterns)

    def test_pulled_custom_roles_stay_in_the_scanned_tree(self):
        patterns = gitignore.load_gitignore_patterns(str(self.root))
        self.assertFalse(
            gitignore.is_path_gitignored(
                f"roles/web-app-cst-demo/{ROLE_FILE_TASKS_MAIN}", patterns
            )
        )

    def test_ignored_files_inside_a_custom_role_stay_ignored(self):
        patterns = gitignore.load_gitignore_patterns(str(self.root))
        self.assertTrue(
            gitignore.is_path_gitignored("roles/web-app-cst-demo/debug.log", patterns)
        )


if __name__ == "__main__":
    unittest.main()
