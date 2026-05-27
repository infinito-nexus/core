#!/usr/bin/env python3

from __future__ import annotations

import stat
import unittest

from . import PROJECT_ROOT


class TestShellScriptsExecutable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = PROJECT_ROOT
        cls.scripts_root = cls.repo_root / "scripts"

    def test_all_shell_scripts_under_scripts_are_executable(self):
        missing_executable_bit: list[str] = []

        for path in sorted(self.scripts_root.rglob("*.sh")):  # nocheck: project-walk
            if not path.is_file():
                continue

            mode = path.stat().st_mode
            has_any_execute_bit = bool(
                mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            )
            if not has_any_execute_bit:
                rel = path.relative_to(self.repo_root).as_posix()
                missing_executable_bit.append(rel)

        if missing_executable_bit:
            self.fail(
                "The following shell scripts are missing the executable bit:\n- "
                + "\n- ".join(missing_executable_bit)
                + "\n\nSet it with: chmod +x <file>"
            )


if __name__ == "__main__":
    unittest.main()
