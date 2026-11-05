"""``resolve/db/primary.sh`` asks the engine's own probe about each instance
and resolves the container of the one it confirms."""

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
    / "db"
    / "primary.sh"
)
CONTAINER_STUB = """#!/usr/bin/env bash
[ "$1 $2" = "service ls" ] && printf '%s\\n' pg_pg-m2 pg_pg-m1 pg_pg-m3
exit 0
"""
PROBE_STUB = """#!/usr/bin/env bash
echo "$1 $2" >> "${PROBE_LOG}"
[ "$2" = "${PRIMARY_KEY}" ]
"""
RESOLVER_STUB = """#!/usr/bin/env bash
printf 'cid-%s\\n' "$2"
"""


class TestResolveDbPrimary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copy(SCRIPT, self.tmp / "resolve-db-primary")
        for name, body in (
            ("resolve-container-id", RESOLVER_STUB),
            ("container", CONTAINER_STUB),
            ("primary-probe-pg", PROBE_STUB),
        ):
            path = self.tmp / name
            path.write_text(body)
            path.chmod(0o755)
        self.log = self.tmp / "probe.log"

    def _run(self, primary, engine="pg"):
        env = {
            **os.environ,
            "PATH": f"{self.tmp}:{os.environ['PATH']}",
            "PRIMARY_KEY": primary,
            "PROBE_LOG": str(self.log),
        }
        return subprocess.run(
            ["bash", str(self.tmp / "resolve-db-primary"), "pg", engine],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_prints_the_container_of_the_confirmed_instance(self):
        result = self._run("pg-m2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "cid-pg-m2")

    def test_probe_gets_stack_and_instance_key(self):
        self._run("pg-m1")
        log = self.log.read_text()  # nocheck: cache-read  the stub appends to this log during the test, a cached read would go stale
        self.assertEqual(log.splitlines()[0], "pg pg-m1")

    def test_no_confirmed_instance_finds_no_primary(self):
        self.assertEqual(self._run("pg-ghost").returncode, 65)

    def test_engine_without_probe_is_refused(self):
        self.assertEqual(self._run("pg-m1", engine="etcd").returncode, 64)


if __name__ == "__main__":
    unittest.main()
