"""``http_primary_probe.sh``, the primary probe of every engine whose
``ha.endpoint`` check is HTTP, maps the check's answer and the instance
resolver's failures onto the probe exit codes."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "sys-svc-compose"
    / "files"
    / "shell"
    / "resolve"
    / "http_primary_probe.sh"
)
CONTAINER_STUB = """#!/usr/bin/env bash
echo "$*" >> "${EXEC_LOG}"
exit "${EXEC_RC}"
"""
RESOLVER_STUB = """#!/usr/bin/env bash
[ -n "${RESOLVE_FAILS}" ] && exit "${RESOLVE_FAILS}"
printf 'cid-%s\\n' "$2"
"""


class TestHttpPrimaryProbe(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copy(SCRIPT, self.tmp / "primary-probe-http")
        for name, body in (
            ("resolve-container-id", RESOLVER_STUB),
            ("container", CONTAINER_STUB),
        ):
            path = self.tmp / name
            path.write_text(body)
            path.chmod(0o755)
        self.log = self.tmp / "exec.log"

    def _run(
        self,
        exec_rc=0,
        resolve_fails="",
        args=("postgres", "postgres-m1", "8008", "/primary"),
    ):
        env = {
            **os.environ,
            "PATH": f"{self.tmp}:{os.environ['PATH']}",
            "EXEC_RC": str(exec_rc),
            "EXEC_LOG": str(self.log),
            "RESOLVE_FAILS": resolve_fails,
        }
        return subprocess.run(
            ["bash", str(self.tmp / "primary-probe-http"), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        ).returncode

    def test_primary_asks_the_check_on_its_port_and_path(self):
        self.assertEqual(self._run(0), 0)
        log = self.log.read_text()  # nocheck: cache-read  the stub appends to this log during the test, a cached read would go stale
        self.assertIn("exec cid-postgres-m1 python3 -c", log)
        self.assertTrue(log.rstrip().endswith("8008 /primary"))

    def test_an_error_status_is_no_primary(self):
        self.assertEqual(self._run(1), 1)

    def test_exec_failures_are_unknown(self):
        for rc in (2, 125, 126, 127):
            with self.subTest(rc=rc):
                self.assertEqual(self._run(rc), 2)

    def test_unresolvable_instance_is_unknown(self):
        for rc in ("64", "65", "66"):
            with self.subTest(rc=rc):
                self.assertEqual(self._run(0, resolve_fails=rc), 2)

    def test_undeployed_instance_is_absent(self):
        self.assertEqual(self._run(0, resolve_fails="67"), 3)

    def test_missing_port_or_path_is_a_usage_error(self):
        self.assertEqual(self._run(0, args=("postgres", "postgres-m1")), 64)


if __name__ == "__main__":
    unittest.main()
