from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

RESOLVER = (
    PROJECT_ROOT
    / "roles"
    / "sys-svc-compose"
    / "files"
    / "shell"
    / "resolve_container_id.sh"
)
STUB = """#!/bin/sh
case "$1 $2" in
"ps --filter") printf '%s\\n' "${FAKE_LOCAL_ID}" | grep . ;;
"node ls") [ -n "${FAKE_MANAGER}" ] ;;
"service ps") printf '%s\\n' "${FAKE_TASK_ID}" | grep . ;;
"inspect --type=task") printf '%s\\n' "${FAKE_TASK_CONTAINER_ID}" | grep . ;;
"inspect --type=container") [ -n "${FAKE_CONTAINER_LOCAL}" ] ;;
*) exit 2 ;;
esac
"""
LOCAL_ID = "0123456789abcdef0123"
REMOTE_ID = "fedcba9876543210fedc"


class TestResolveContainerId(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.bin = Path(self._tmp.name)
        stub = self.bin / "container"
        stub.write_text(STUB)
        stub.chmod(0o755)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def resolve(self, **fake: str) -> subprocess.CompletedProcess:
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_LOCAL_ID": "",
            "FAKE_MANAGER": "",
            "FAKE_TASK_ID": "",
            "FAKE_TASK_CONTAINER_ID": "",
            "FAKE_CONTAINER_LOCAL": "",
        }
        env.update(fake)
        return subprocess.run(
            ["/bin/bash", str(RESOLVER), "stack", "app"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_a_worker_with_a_local_task_prints_its_short_id(self) -> None:
        done = self.resolve(FAKE_LOCAL_ID=LOCAL_ID)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, f"{LOCAL_ID[:12]}\n")

    def test_a_worker_without_a_local_task_exits_64(self) -> None:
        done = self.resolve()
        self.assertEqual(done.returncode, 64)
        self.assertEqual(done.stdout, "")
        self.assertIn("only a Swarm manager can look further", done.stderr)

    def test_a_manager_without_any_running_task_exits_65(self) -> None:
        done = self.resolve(FAKE_MANAGER="1")
        self.assertEqual(done.returncode, 65)

    def test_a_manager_whose_task_runs_elsewhere_exits_66(self) -> None:
        done = self.resolve(
            FAKE_MANAGER="1", FAKE_TASK_ID="task", FAKE_TASK_CONTAINER_ID=REMOTE_ID
        )
        self.assertEqual(done.returncode, 66)

    def test_missing_arguments_exit_64(self) -> None:
        done = subprocess.run(
            ["/bin/bash", str(RESOLVER), "stack"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.returncode, 64)


if __name__ == "__main__":
    unittest.main()
