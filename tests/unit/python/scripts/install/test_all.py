"""Contract of the incremental install stamp: the install chain re-runs only
when the content of a recipe input changed, so a commit hook that rewrites an
input unchanged (and bumps its mtime) keeps the stamp valid."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

ALL = "scripts/install/all.sh"
PYTHON_ENV = "scripts/meta/env/python.sh"
BOOTSTRAP = "bootstrap/install.sh"
STEPS = (
    "scripts/install/python.sh",
    "scripts/install/ansible.sh",
    "scripts/install/venv.sh",
)
INPUTS = (
    "pyproject.toml",
    "requirements/requirements.galaxy.yml",
    "requirements/requirements.git.yml",
)
STEP_STUB = '#!/usr/bin/env bash\nprintf "%s\\n" "$0" >>"${INSTALL_LOG}"\n'


class TestInstallStamp(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "repo"
        for rel in (ALL, PYTHON_ENV):
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / rel, target)
        (self.root / "default.env").write_text(
            f"INFINITO_PYTHON_INSTALL_SCRIPT={BOOTSTRAP}\n"
        )
        self.contents = dict.fromkeys((*STEPS, BOOTSTRAP), STEP_STUB) | {
            rel: f"{rel}\n" for rel in INPUTS
        }
        for rel, content in self.contents.items():
            self._write(rel, content)
        venv = Path(tmp.name) / "venv"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").symlink_to(shutil.which("python3"))
        self.log = Path(tmp.name) / "install.log"
        self.env = {
            "HOME": tmp.name,
            "PATH": os.environ["PATH"],
            "VENV": str(venv),
            "INSTALL_LOG": str(self.log),
        }

    def _write(self, rel: str, content: str) -> None:
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def _logged(self) -> int:
        if not self.log.exists():
            return 0
        with self.log.open() as handle:
            return sum(1 for _ in handle)

    def _runs(self) -> int:
        before = self._logged()
        subprocess.run(
            ["bash", str(self.root / ALL)],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )
        return self._logged() - before

    def _rewrite_unchanged(self) -> None:
        future = time.time() + 120
        for rel, content in self.contents.items():
            self._write(rel, content)
            os.utime(self.root / rel, (future, future))

    def test_first_run_installs_every_step(self) -> None:
        self.assertEqual(self._runs(), len(STEPS) + 1)

    def test_unchanged_rewrite_keeps_the_stamp(self) -> None:
        self._runs()
        self._rewrite_unchanged()
        self.assertEqual(self._runs(), 0)

    def test_negative_control_changed_input_reinstalls(self) -> None:
        self._runs()
        self._write(INPUTS[0], "changed\n")
        self.assertEqual(self._runs(), len(STEPS) + 1)

    def test_missing_input_fails(self) -> None:
        (self.root / INPUTS[1]).unlink()
        result = subprocess.run(
            ["bash", str(self.root / ALL)],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            (result.returncode, result.stderr.strip()),
            (1, f"[install] missing dependency: {INPUTS[1]}"),
        )


if __name__ == "__main__":
    unittest.main()
