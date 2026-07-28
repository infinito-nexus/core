"""The .env generator must import and run without any third-party module.

The dev-environment suite runs the generator inside a bare distro image,
before any dependency is installed. This probes the whole import closure of
``cli.meta.env`` plus every handler call, with non-stdlib imports blocked.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT

PROBE = PROJECT_ROOT / "tests" / "utils" / "bare_bootstrap_probe.py"

GUIDANCE = (
    "The .env generator must import and run on the bare bootstrap python, "
    "so every module it reaches at import time and at call time has to be "
    "stdlib-only. Read SPOT files with utils.cache.files.read_text plus "
    "utils.yaml_bootstrap.load_block or a stdlib line parse, never through "
    "utils.cache.yaml."
)


class TestBareBootstrap(unittest.TestCase):
    def _run(self, overlay: dict[str, str]) -> str:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("INFINITO_", "GITHUB_")) and k != "ACT"
        }
        env.update(overlay)
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(PROBE),
                    str(PROJECT_ROOT),
                    str(Path(td) / ".env"),
                ],
                env=env,
                cwd=str(PROJECT_ROOT),
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(
            result.returncode,
            0,
            f"{GUIDANCE}\n\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result.stdout.strip()

    def test_generator_runs_without_third_party_modules(self) -> None:
        self.assertTrue(int(self._run({})) > 0)

    def test_generator_runs_on_the_github_actions_branch(self) -> None:
        overlay = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY_OWNER": "acme"}
        self.assertTrue(int(self._run(overlay)) > 0)


if __name__ == "__main__":
    unittest.main()
