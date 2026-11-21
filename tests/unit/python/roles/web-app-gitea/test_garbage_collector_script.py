from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "web-app-gitea"
    / "files"
    / "shell"
    / "garbage_collector.sh"
)
CONTAINER_ROOT = "/data/git/repositories"

FAKE_CONTAINER = f"""#!/bin/sh
[ "$1" = exec ] && [ "$2" = -u ] || exit 2
if [ -n "$FAKE_EXEC_FAIL" ]; then
  echo "container is not running" >&2
  exit 1
fi
shift 4
for arg do
  shift
  [ "$arg" = {CONTAINER_ROOT} ] && arg="$FAKE_ROOT"
  set -- "$@" "$arg"
done
exec "$@"
"""


class TestGiteaGcScript(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.bin = base / "bin"
        self.bin.mkdir()
        fake = self.bin / "container"
        fake.write_text(FAKE_CONTAINER)
        fake.chmod(0o755)
        self.root = base / "repositories"
        self.pack = self.root / "org" / "repo.git" / "objects" / "pack"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _file(self, name: str, age_minutes: int) -> Path:
        self.pack.mkdir(parents=True, exist_ok=True)
        path = self.pack / name
        path.write_text("x")
        stamp = time.time() - age_minutes * 60
        os.utime(path, (stamp, stamp))
        return path

    def _run(self, mode: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["/bin/bash", str(SCRIPT), mode],
            env={
                "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                "GARBAGE_COLLECTOR_ADDRESS": "gitea",
                "GARBAGE_COLLECTOR_APP_TIMEOUT": "30",
                "GITEA_GARBAGE_COLLECTOR_MINUTES_ROUTINE": "60",
                "GITEA_GARBAGE_COLLECTOR_MINUTES_PRESSURE": "10",
                "FAKE_ROOT": str(self.root),
                **extra,
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def test_a_fresh_instance_without_repositories_exits_zero(self) -> None:
        result = self._run("routine")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing to clean", result.stdout)

    def test_routine_removes_only_leftovers_older_than_its_age(self) -> None:
        old = self._file("tmp_pack_old", 120)
        young = self._file("tmp_pack_young", 30)
        pack = self._file("pack-abc.pack", 120)
        result = self._run("routine")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(old.exists())
        self.assertTrue(young.exists())
        self.assertTrue(pack.exists())
        self.assertIn("tmp_pack_old", result.stdout)

    def test_pressure_uses_its_shorter_age(self) -> None:
        young = self._file("tmp_pack_young", 30)
        result = self._run("pressure")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(young.exists())

    def test_an_unreachable_container_fails_the_run(self) -> None:
        result = self._run("routine", FAKE_EXEC_FAIL="1")
        self.assertNotEqual(result.returncode, 0)

    def test_an_unknown_mode_is_a_usage_error(self) -> None:
        self.assertEqual(self._run("purge").returncode, 64)
