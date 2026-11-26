from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

RUN_SCRIPT = PROJECT_ROOT / "scripts" / "tests" / "code" / "run.sh"
PYTHON_STUB = """#!/usr/bin/env bash
if [ "$1" = "-c" ]; then
\texec @PYTHON@ "$@"
fi
if [ "$1" = "-m" ]; then
\tprintf 'PYTHONPYCACHEPREFIX=%s\\n' "${PYTHONPYCACHEPREFIX-<unset>}"
\tprintf 'PYTHONDONTWRITEBYTECODE=%s\\n' "${PYTHONDONTWRITEBYTECODE-<unset>}"
fi
exit 0
""".replace("@PYTHON@", sys.executable)
NO_OP = "#!/usr/bin/env bash\nexit 0\n"
UNSET = "<unset>"


def _executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def _printed(output: str) -> dict[str, str]:
    keys = ("PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE")
    return {
        key: value
        for key, _, value in (line.partition("=") for line in output.splitlines())
        if key in keys
    }


class TestRunBytecode(unittest.TestCase):
    def setUp(self) -> None:
        checkout = tempfile.TemporaryDirectory()
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(checkout.cleanup)
        self.addCleanup(scratch.cleanup)
        self.root = Path(checkout.name).resolve()
        self.scratch = Path(scratch.name).resolve()
        code = self.root / "scripts" / "tests" / "code"
        code.mkdir(parents=True)
        shutil.copy(RUN_SCRIPT, code / "run.sh")
        _executable(self.root / "scripts" / "meta" / "env" / "load.sh", ":\n")
        _executable(self.root / "scripts" / "install" / "dev-extras.sh", NO_OP)
        _executable(self.root / "bin" / "make", NO_OP)
        _executable(self.root / "bin" / "python", PYTHON_STUB)
        self.prefix = self.root / "build" / f"pycache-{os.getuid()}" / "unit"

    def _run(self, on_github: str, tmpdir: Path) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("INFINITO_", "PYTHON", "PARALLEL_"))
            and key not in ("BASH_ENV", "PWD", "TMPDIR", "test_paths")
        } | {
            "INFINITO_RUNNING_ON_GITHUB": on_github,
            "INFINITO_TEST_PATTERN": "test*.py",
            "INFINITO_TEST_TYPE": "unit",  # nocheck: makefile-supplied
            "PYTHON": str(self.root / "bin" / "python"),
            "TMPDIR": str(tmpdir),
        }
        proc = subprocess.run(
            ["bash", str(self.root / "scripts" / "tests" / "code" / "run.sh")],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return _printed(proc.stdout)

    def _cached(self, source_dir: Path) -> Path:
        pyc = self.prefix / source_dir.relative_to("/") / "mod.cpython-314.pyc"
        pyc.parent.mkdir(parents=True)
        pyc.write_text("")
        return pyc

    def test_a_local_run_writes_bytecode_below_build_per_suite(self) -> None:
        self.assertEqual(
            self._run("false", self.scratch),
            {"PYTHONPYCACHEPREFIX": str(self.prefix), "PYTHONDONTWRITEBYTECODE": UNSET},
        )

    def test_a_local_run_drops_scratch_bytecode_and_keeps_the_checkouts(self) -> None:
        stale = self._cached(self.scratch / "tmpabc")
        kept = self._cached(self.root / "utils")

        self._run("false", self.scratch)

        self.assertFalse(stale.exists())
        self.assertFalse((self.prefix / self.scratch.relative_to("/")).exists())
        self.assertTrue(kept.exists())

    def test_a_checkout_below_the_scratch_root_keeps_its_bytecode(self) -> None:
        kept = self._cached(self.root / "utils")

        self._run("false", self.root.parent)

        self.assertTrue(kept.exists())

    def test_a_github_run_writes_no_bytecode(self) -> None:
        stale = self._cached(self.scratch / "tmpabc")

        self.assertEqual(
            self._run("true", self.scratch),
            {"PYTHONPYCACHEPREFIX": UNSET, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertTrue(stale.exists())


if __name__ == "__main__":
    unittest.main()
