"""Forbid ``sudo -E`` and bare ``sudo --preserve-env`` in tracked .yml and .sh files."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_WHOLE_ENV = re.compile(r"\bsudo\s+(?:-\w+\s+)*(?:-\w*E\w*|--preserve-env)(?=\s|$)")


class TestNoSudoPreserveWholeEnv(unittest.TestCase):
    def test_no_whole_environment_preservation(self) -> None:
        offenders: list[str] = []
        for path_str in iter_project_files(
            extensions=(".yml", ".yaml", ".sh"),
            exclude_tests=True,
            exclude_dirs=("docs",),
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            for lineno, line in enumerate(read_text(path_str).splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if _WHOLE_ENV.search(line):
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")

        if offenders:
            self.fail(
                f"{len(offenders)} sudo call(s) preserve the whole environment. "
                "sudo-rs (default sudo on ubuntu-26.04 runners) ignores -E and "
                "drops every caller variable; name them instead with "
                '--preserve-env="$(compgen -e | paste -sd, -)".\n'
                + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
