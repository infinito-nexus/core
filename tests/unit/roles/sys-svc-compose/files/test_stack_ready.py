"""Behaviour of the swarm convergence gate.

``stack_ready.sh`` decides whether a swarm deploy is done. It is driven by an
Ansible ``until`` loop of up to 150 polls, so both its verdict and how much it
prints on a failing poll matter. Exercised here against a stub docker: a fully
replicated stack passes, a short one fails, a completed one-shot counts as done,
and a non-converged service reports the task rows that carry an error while
staying quiet about the ones that do not.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

GATE = PROJECT_ROOT / "roles" / "sys-svc-compose" / "files" / "swarm" / "stack_ready.sh"
STUB = """#!/usr/bin/env bash
case "$1 $2" in
"stack services") printf '%s' "${STACK_SERVICES}" ;;
"service ps") printf '%s' "${SERVICE_PS}" ;;
esac
exit 0
"""


class TestStackReady(unittest.TestCase):
    def _run(self, services: str, service_ps: str = "") -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            stub_bin = Path(tmp) / "bin"
            stub_bin.mkdir()
            docker = stub_bin / "docker"
            docker.write_text(STUB)
            docker.chmod(0o755)
            timeout = stub_bin / "timeout"
            timeout.write_text('#!/usr/bin/env bash\nshift\nexec "$@"\n')
            timeout.chmod(0o755)

            env = dict(os.environ)
            env.update(
                STACK="demo",
                STACK_SERVICES=services,
                SERVICE_PS=service_ps,
                PATH=f"{stub_bin}:{env['PATH']}",
                BASH_ENV="",
            )
            return subprocess.run(
                ["bash", str(GATE)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_a_fully_replicated_stack_converges(self) -> None:
        proc = self._run("demo_web 3/3\ndemo_db 1/1\n")
        self.assertEqual(proc.returncode, 0)

    def test_a_short_service_does_not_converge(self) -> None:
        proc = self._run("demo_web 2/3\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not converged", proc.stderr)
        self.assertIn("demo_web", proc.stderr)

    def test_a_completed_oneshot_counts_as_converged(self) -> None:
        proc = self._run(
            "demo_init 0/1\n",
            "demo_init.1|Shutdown|Complete 3 minutes ago\n",
        )
        self.assertEqual(proc.returncode, 0)

    def test_a_task_error_reaches_the_caller(self) -> None:
        proc = self._run(
            "demo_reg 0/1\n",
            "demo_reg.1 desired=Running current=Preparing error=manifest pull timed out\n",
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("manifest pull timed out", proc.stderr)

    def test_error_free_task_rows_are_not_echoed(self) -> None:
        proc = self._run(
            "demo_slow 0/1\n",
            "demo_slow.1 desired=Running current=Preparing error=\n",
        )
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("demo_slow.1", proc.stderr)


if __name__ == "__main__":
    unittest.main()
