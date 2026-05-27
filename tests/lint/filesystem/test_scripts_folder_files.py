"""Lint check: tracked files under scripts/ must be shell scripts.

README.md files are ignored because they are documentation-only exceptions.
"""

from __future__ import annotations

import subprocess
import unittest
from typing import TYPE_CHECKING

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path


def tracked_files(root: Path) -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z"],
            stderr=subprocess.STDOUT,
        )
        rel_paths = [path for path in output.decode("utf-8").split("\0") if path]
        return [root / rel_path for rel_path in rel_paths]
    except Exception:
        return [
            path
            for path in root.rglob("*")  # nocheck: project-walk
            if path.is_file()
            and ".git" not in path.parts
            and "__pycache__" not in path.parts
        ]


class TestScriptsFolderFiles(unittest.TestCase):
    def test_scripts_contains_only_sh_files(self) -> None:
        root = PROJECT_ROOT
        scripts_root = root / "scripts"

        violations = [
            path.relative_to(root).as_posix()
            for path in tracked_files(root)
            if path.is_relative_to(scripts_root)
            and path.name != "README.md"
            and path.suffix != ".sh"
        ]

        self.assertEqual(
            violations,
            [],
            "Tracked files under scripts/ must end with .sh "
            "(README.md is allowed).\nFound:\n"
            + "\n".join(f"  {path}" for path in sorted(violations)),
        )


if __name__ == "__main__":
    unittest.main()
