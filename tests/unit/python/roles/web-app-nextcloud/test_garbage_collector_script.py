from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "web-app-nextcloud"
    / "files"
    / "shell"
    / "garbage_collector.sh"
)

FAKE_CONTAINER = """#!/bin/sh
printf '%s\\n' "$*" >>"$FAKE_LOG"
[ -z "$FAKE_FAIL_ON" ] || case "$*" in *"$FAKE_FAIL_ON"*) exit 1 ;; esac
"""
OCC = "exec -u www-data nextcloud timeout 30 /var/www/html/occ"


class TestNextcloudGcScript(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.bin = base / "bin"
        self.bin.mkdir()
        fake = self.bin / "container"
        fake.write_text(FAKE_CONTAINER)
        fake.chmod(0o755)
        self.log = base / "calls.log"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, mode: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["/bin/bash", str(SCRIPT), mode],
            env={
                "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                "GARBAGE_COLLECTOR_ADDRESS": "nextcloud",
                "GARBAGE_COLLECTOR_APP_TIMEOUT": "30",
                "NEXTCLOUD_GARBAGE_COLLECTOR_USER": "www-data",
                "NEXTCLOUD_GARBAGE_COLLECTOR_OCC": "/var/www/html/occ",
                "FAKE_LOG": str(self.log),
                "FAKE_FAIL_ON": "",
                **extra,
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def _calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return self.log.read_text().splitlines()  # nocheck: cache-read  stub call log

    def test_routine_expires_the_trash_bin(self) -> None:
        result = self._run("routine")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._calls(), [f"{OCC} trashbin:expire"])

    def test_pressure_also_drops_the_previews(self) -> None:
        result = self._run("pressure")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self._calls(),
            [f"{OCC} trashbin:expire", f"{OCC} preview:cleanup"],
        )

    def test_a_failing_occ_command_fails_the_run(self) -> None:
        result = self._run("pressure", FAKE_FAIL_ON="trashbin:expire")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._calls(), [f"{OCC} trashbin:expire"])

    def test_an_unknown_mode_exits_64_without_touching_the_container(self) -> None:
        result = self._run("everything")
        self.assertEqual(result.returncode, 64)
        self.assertEqual(self._calls(), [])


if __name__ == "__main__":
    unittest.main()
