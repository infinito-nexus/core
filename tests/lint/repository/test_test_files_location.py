from __future__ import annotations

import os
import unittest
from pathlib import Path

from utils.cache.base import PROJECT_ROOT
from utils.cache.files import iter_project_files
from utils.cache.gitignore import is_path_gitignored, load_gitignore_patterns


class TestTestFilesLocation(unittest.TestCase):
    """
    Test-linter that enforces every `test_*.py` file to live under the
    top-level `tests/` directory.

    Files matched by `.gitignore` are skipped via the SPOT helpers in
    :mod:`utils.cache.files`, so the lint works in environments where
    `.git/` is not mounted (e.g. the `make exec` container).
    """

    def test_no_test_files_outside_tests_dir(self):
        root = PROJECT_ROOT
        patterns = load_gitignore_patterns(str(root))

        offenders: list[str] = []
        for path_str in iter_project_files(extensions=(".py",)):
            if os.path.basename(path_str).startswith("test_") is False:
                continue
            rel = Path(path_str).relative_to(root).as_posix()
            if rel == "tests" or rel.startswith("tests/"):
                continue
            if is_path_gitignored(rel, patterns):
                continue
            offenders.append(rel)

        if offenders:
            self.fail(
                "Found `test_*.py` files outside the top-level `tests/` "
                "directory. Move them under `tests/` (or add them to "
                "`.gitignore` if they are not real tests):\n"
                + "\n".join(f"- {p}" for p in sorted(offenders))
            )


if __name__ == "__main__":
    unittest.main()
