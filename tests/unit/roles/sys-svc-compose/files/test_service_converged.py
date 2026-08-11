"""Behaviour of the swarm service convergence probe.

``service_converged.sh`` gates a swarm deploy on one service and is driven by an
Ansible ``until`` loop of up to 600 polls, so both its verdict and how much it
prints on a failing poll matter. Exercised here against a stub docker: a running
service passes silently, every refusal names its reason on stderr, and only the
branch that has task rows to show prints them, filtered to the rows carrying an
error.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

PROBE = (
    PROJECT_ROOT
    / "roles"
    / "sys-svc-compose"
    / "files"
    / "swarm"
    / "service_converged.sh"
)
STUB = """#!/usr/bin/env bash
case "$1 $2" in
"service inspect") printf '%s' "${UPDATE_STATE}" ;;
"service ps")
	case "$*" in
	*--filter*) printf '%s' "${FILTERED_PS}" ;;
	*) printf '%s' "${FULL_PS}" ;;
	esac
	;;
esac
exit "${PS_RC:-0}"
"""


class TestServiceConverged(unittest.TestCase):
    def _run(
        self,
        update_state: str = "",
        filtered_ps: str = "",
        full_ps: str = "",
        ps_rc: str = "0",
    ) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            stub_bin = Path(tmp) / "bin"
            stub_bin.mkdir()
            container = stub_bin / "container"
            container.write_text(STUB)
            container.chmod(0o755)
            timeout = stub_bin / "timeout"
            timeout.write_text('#!/usr/bin/env bash\nshift\nexec "$@"\n')
            timeout.chmod(0o755)
            env = dict(os.environ)
            env.update(
                {
                    "PATH": f"{stub_bin}:{env['PATH']}",
                    "SERVICE": "demo_app",
                    "UPDATE_STATE": update_state,
                    "FILTERED_PS": filtered_ps,
                    "FULL_PS": full_ps,
                    "PS_RC": ps_rc,
                }
            )
            return subprocess.run(
                ["bash", str(PROBE)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_running_service_passes_without_output(self):
        proc = self._run(
            update_state="completed", filtered_ps="Running 2 minutes ago\n"
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, "")

    def test_update_in_progress_is_worth_another_poll(self):
        proc = self._run(update_state="updating", filtered_ps="Running 2 minutes ago\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("UpdateStatus.State=updating", proc.stderr)

    def test_latched_update_gives_up_instead_of_polling(self):
        for latched in ("paused", "rollback_paused"):
            with self.subTest(state=latched):
                proc = self._run(
                    update_state=latched,
                    filtered_ps="Running 2 minutes ago\n",
                    full_ps="demo_app.1 node-a Shutdown Failed error=task: non-zero exit (1)\n",
                )
                self.assertEqual(proc.returncode, 2)
                self.assertIn(f"UpdateStatus.State={latched}", proc.stderr)
                self.assertIn("cannot leave this state on its own", proc.stderr)

    def test_missing_desired_running_task_is_named(self):
        proc = self._run(filtered_ps="")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no task carries desired-state=running", proc.stderr)

    def test_failing_service_ps_is_named_instead_of_leaking_its_code(self):
        proc = self._run(ps_rc="124")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("service ps failed or timed out", proc.stderr)

    def test_pending_tasks_report_only_the_rows_carrying_an_error(self):
        proc = self._run(
            filtered_ps="Preparing\n",
            full_ps=(
                "demo_app.1 node-a Running Preparing error=\n"
                "demo_app.2 node-b Shutdown Failed error=task: non-zero exit (1)\n"
            ),
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("tasks not running yet", proc.stderr)
        self.assertIn("demo_app.2", proc.stderr)
        self.assertNotIn("demo_app.1", proc.stderr)


if __name__ == "__main__":
    unittest.main()
