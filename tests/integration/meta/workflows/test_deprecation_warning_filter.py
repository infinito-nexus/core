from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "scripts"
    / "tests"
    / "deploy"
    / "ci"
    / "assert_no_deprecation_warnings.sh"
)

_CLEAN_LOG = """\
PLAY [deploy] ******************************************************************
TASK [web-app-x : do thing] ***************************************************
ok: [host]
PLAY RECAP *******************************************************************
host : ok=1 changed=0 unreachable=0 failed=0
"""

_DEPRECATION_LOG = """\
PLAY [deploy] ******************************************************************
[DEPRECATION WARNING]: Ansible will require Python 3.x. This feature will be
removed in a future release.
ok: [host]
"""


class TestDeprecationWarningFilter(unittest.TestCase):
    def _run(self, log_path: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SCRIPT), log_path],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            check=False,
        )

    def _write_log(self, tmp: Path, content: str) -> str:
        log = tmp / "deploy.log"
        log.write_text(content, encoding="utf-8")
        return str(log)

    def test_clean_log_passes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            res = self._run(self._write_log(Path(d), _CLEAN_LOG))
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_deprecation_log_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            res = self._run(self._write_log(Path(d), _DEPRECATION_LOG))
        self.assertEqual(res.returncode, 1)
        self.assertIn("[DEPRECATION WARNING]:", res.stderr)

    def test_missing_log_errors(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            res = self._run(str(Path(d) / "nope.log"))
        self.assertEqual(res.returncode, 2)


if __name__ == "__main__":
    unittest.main()
