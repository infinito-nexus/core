"""The caller contract of the rescue-artifact index.

``rescue_index.sh`` runs inside cleanup handlers and in a GitHub step under
``bash -e`` with no fallback, so its exit status decides whether the caller
finishes tearing down: a fatal usage error and a ``find`` that rejects
``-printf`` both have to leave the caller at rc 0, and the latter has to stay
distinguishable from an empty tree rather than reporting one.

The tree is indexed while a failed run is still being torn down, so a walk that
dies partway is the normal case, not the exception. What ``find`` reached before
it failed is the evidence the artifact is being read for, so it has to survive.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

INDEX = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "utils" / "rescue_index.sh"
FIND_WITHOUT_PRINTF = '#!/bin/sh\necho "find: unrecognized: -printf" >&2\nexit 1\n'
GLYPHS = ("📁", "📄", "📜", "🧾")
FIND_CUT_SHORT = (
    "#!/bin/sh\n"
    "printf 'd         80 logs\\n'\n"
    "printf 'f          9 logs/container.log\\n'\n"
    "printf 'f         12 inspect.json\\n'\n"
    "echo \"find: 'logs/vanished': No such file or directory\" >&2\n"
    "exit 1\n"
)


class TestRescueIndexContract(unittest.TestCase):
    def _run(
        self, *args: str, stub_find: str | None = None
    ) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        with tempfile.TemporaryDirectory() as tmp:
            if stub_find is not None:
                stub_bin = Path(tmp) / "bin"
                stub_bin.mkdir()
                find = stub_bin / "find"
                find.write_text(stub_find)
                find.chmod(0o755)
                env["PATH"] = f"{stub_bin}:{env['PATH']}"
            return subprocess.run(
                ["bash", str(INDEX), *args],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_a_fatal_error_does_not_reach_the_caller(self) -> None:
        self.assertEqual(self._run().returncode, 0)

    def test_a_failed_walk_neither_aborts_nor_looks_like_an_empty_tree(self) -> None:
        with (
            tempfile.TemporaryDirectory() as populated,
            tempfile.TemporaryDirectory() as empty,
        ):
            (Path(populated) / "a").mkdir()
            (Path(populated) / "a" / "collected.log").write_text("evidence")

            broken = self._run(populated, stub_find=FIND_WITHOUT_PRINTF)
            genuinely_empty = self._run(empty)

        self.assertEqual(broken.returncode, 0)
        self.assertNotEqual(
            broken.stdout.replace(populated, ""),
            genuinely_empty.stdout.replace(empty, ""),
        )

    def test_a_walk_cut_short_still_lists_what_it_reached(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = self._run(td, stub_find=FIND_CUT_SHORT)

        self.assertEqual(result.returncode, 0)
        for reached in ("logs", "container.log", "inspect.json"):
            self.assertIn(reached, result.stdout)
        self.assertIn("2 file(s)", result.stdout)

    def test_a_child_is_indented_under_its_parent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = self._run(td, stub_find=FIND_CUT_SHORT)

        indent = {}
        for line in result.stdout.splitlines():
            entry = line.lstrip()
            if entry[:1] not in GLYPHS:
                continue
            name = entry.split(None, 1)[1].split("  (")[0]
            indent[name] = len(line) - len(entry)

        self.assertLess(indent["logs/"], indent["container.log"])
        self.assertEqual(indent["logs/"], indent["inspect.json"])


if __name__ == "__main__":
    unittest.main()
