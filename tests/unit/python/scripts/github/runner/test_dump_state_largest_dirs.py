from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

SCRIPT = PROJECT_ROOT / "scripts" / "github" / "runner" / "dump_state.sh"
FUNCTION_RE = re.compile(r"^largest_dirs\(\) \{\n.*?^\}\n", re.MULTILINE | re.DOTALL)
TOP_DIRS = 2
SUB_DIRS = 4
SLOW_S = 1
SERIAL_S = TOP_DIRS * SUB_DIRS * SLOW_S
DEADLINE_S = 30
SERIAL_LISTING = 'du -xh --max-depth=2 "$1" 2>/dev/null | sort -h | tail -15'
PASS_THROUGH_SUDO = '#!/usr/bin/env bash\nexec "$@"\n'
SLOW_WARM_UP_DU = (
    "#!/usr/bin/env bash\n"
    'if [ "$1" = -xs ]; then\n'
    '\tprintf "%s\\n" "$2" >>"${STUB_WARM_LOG}"\n'
    '\tsleep "${STUB_SLOW_S}"\n'
    "fi\n"
    'PATH="${STUB_REAL_PATH}" exec du "$@"\n'
)


def largest_dirs_source() -> str:
    """Cut the largest_dirs function out of dump_state.sh.

    Returns:
        The function definition as bash source.
    """
    match = FUNCTION_RE.search(read_text(str(SCRIPT)))
    if match is None:
        raise AssertionError(f"{SCRIPT} defines no largest_dirs function")
    return match.group(0)


class LargestDirsCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.tree = self.tmp / "tree"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.warm_log = self.tmp / "warm.log"
        for top in range(TOP_DIRS):
            for sub in range(SUB_DIRS):
                leaf = self.tree / f"top{top}" / f"sub{sub}" / "deep"
                leaf.mkdir(parents=True)
                (leaf / "data").write_bytes(b"x" * 4096 * (1 + top * SUB_DIRS + sub))
        self.stub("sudo", PASS_THROUGH_SUDO)
        self.env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "STUB_REAL_PATH": os.environ["PATH"],
            "STUB_WARM_LOG": str(self.warm_log),
            "STUB_SLOW_S": str(SLOW_S),
        }

    def stub(self, name: str, body: str) -> None:
        """Put an executable stub in front of PATH.

        Args:
            name: command the stub replaces.
            body: the stub's bash source.
        """
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)

    def largest_dirs(self) -> subprocess.CompletedProcess[str]:
        """Run the function from dump_state.sh over the test tree.

        Returns:
            The finished bash process.
        """
        program = f'set -euo pipefail\n{largest_dirs_source()}largest_dirs "$1"\n'
        return subprocess.run(
            ["bash", "-c", program, "_", str(self.tree)],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=DEADLINE_S,
            check=False,
        )


class TestLargestDirs(LargestDirsCase):
    def test_listing_matches_the_serial_du(self) -> None:
        expected = subprocess.run(
            ["bash", "-c", SERIAL_LISTING, "_", str(self.tree)],
            capture_output=True,
            text=True,
            timeout=DEADLINE_S,
            check=True,
        ).stdout
        done = self.largest_dirs()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, expected)

    def test_warm_up_walks_every_second_level_directory_in_parallel(self) -> None:
        self.stub("du", SLOW_WARM_UP_DU)
        started = time.monotonic()
        done = self.largest_dirs()
        elapsed = time.monotonic() - started
        self.assertEqual(done.returncode, 0, done.stderr)
        warmed = sorted(
            self.warm_log.read_text().splitlines()  # nocheck: cache-read  stub call log
        )
        self.assertEqual(
            warmed,
            sorted(
                str(self.tree / f"top{top}" / f"sub{sub}")
                for top in range(TOP_DIRS)
                for sub in range(SUB_DIRS)
            ),
        )
        self.assertLess(elapsed, SERIAL_S / 2)


if __name__ == "__main__":
    unittest.main()
