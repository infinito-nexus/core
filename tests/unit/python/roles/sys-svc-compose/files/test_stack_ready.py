"""Behaviour of the swarm convergence gate.

``stack_ready.sh`` decides whether a swarm deploy is done. It is driven by an
Ansible ``until`` loop that keeps polling on rc 1 and gives up at once on rc 2,
so both its verdict and how much it prints on a failing poll matter. Exercised
here against a stub docker: a fully replicated stack passes, a short one keeps
the caller waiting, a completed one-shot counts as done, and every task row
reaches the caller.

The two terminal verdicts are split by the task's current state, because that is
what says whether docker ever ran the container. A task rejected or left
unschedulable never started, so docker has already judged the spec unrunnable
and the verdict needs no clock. A task that failed did run, and a crash loop
waiting out a dependency is indistinguishable from one that never converges, so
only the grace-gated strike counter may end it - never on the newest row alone,
and never on errors left below a finished attempt. That counter is armed off the
service's own ``UpdatedAt``, so an unreadable epoch has to keep the caller
waiting rather than arm it.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

GATE = (
    PROJECT_ROOT
    / "roles"
    / "sys-svc-compose"
    / "files"
    / "shell"
    / "swarm"
    / "stack_ready.sh"
)
STUB = """#!/usr/bin/env bash
case "$1 $2" in
"stack services") printf '%s' "${STACK_SERVICES}" ;;
"service inspect") printf '%s' "${SERVICE_UPDATED_AT}" ;;
"service ps")
	case "$5" in
	*'{{.Name}}|{{.CurrentState}}|{{.Error}}'*) printf '%s' "${SERVICE_ERRORS}" ;;
	*) printf '%s' "${SERVICE_PS}" ;;
	esac
	;;
esac
exit 0
"""


class TestStackReady(unittest.TestCase):
    def _run(
        self,
        services: str,
        service_ps: str = "",
        service_errors: str = "",
        churning: int = 0,
        updated_at: str | None = None,
    ) -> subprocess.CompletedProcess:
        """Poll the gate once, ``churning`` seconds into a non-converged deploy.

        Args:
            services: ``docker stack services`` table the stub returns.
            service_ps: verbose ``docker service ps`` table for the report.
            service_errors: ``name|current state|error`` rows, newest first.
            churning: seconds since the deploy bumped the service ``UpdatedAt``.
            updated_at: raw ``UpdatedAt`` epoch, overriding ``churning``.
        """
        if updated_at is None:
            updated_at = str(int(time.time()) - churning)
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
                FATAL_GRACE="180",
                STACK_SERVICES=services,
                SERVICE_PS=service_ps,
                SERVICE_ERRORS=service_errors,
                SERVICE_UPDATED_AT=updated_at,
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

    def test_a_rejected_task_is_terminal_without_any_grace(self) -> None:
        proc = self._run(
            "demo_reg 0/1\n",
            "demo_reg.1 desired=Ready current=Rejected error=No such image: reg/nope\n",
            "demo_reg.1|Rejected 3 seconds ago|No such image: reg/nope\n",
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("No such image", proc.stderr)
        self.assertIn("stuck: demo_reg", proc.stderr)

    def test_an_unschedulable_task_is_terminal_without_any_grace(self) -> None:
        proc = self._run(
            "demo_place 0/1\n",
            "demo_place.1 desired=Running current=Pending error=no suitable node\n",
            "demo_place.1|Pending 28 seconds ago|no suitable node\n",
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("stuck: demo_place", proc.stderr)

    def test_a_newest_failed_attempt_alone_is_never_terminal(self) -> None:
        """A container that ran and died may still be waiting out a dependency."""
        proc = self._run(
            "demo_boot 0/1\n",
            "demo_boot.1 desired=Shutdown current=Failed error=task: non-zero exit (1)\n",
            "demo_boot.1|Failed 1 second ago|task: non-zero exit (1)\n",
        )
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("stuck:", proc.stderr)

    def test_error_free_task_rows_are_echoed_and_keep_the_caller_waiting(self) -> None:
        proc = self._run(
            "demo_slow 0/1\n",
            "demo_slow.1 desired=Running current=Preparing error=\n",
            "demo_slow.1|Preparing 2 seconds ago|\n",
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("demo_slow.1", proc.stderr)
        self.assertIn("current=Preparing", proc.stderr)

    def test_a_fresh_attempt_after_two_failures_still_waits(self) -> None:
        proc = self._run(
            "demo_boot 0/1\n",
            "demo_boot.1 desired=Running current=Starting error=\n",
            "demo_boot.1|Ready 1 second ago|\n"
            "demo_boot.1|Failed 2 seconds ago|task: non-zero exit (1)\n"
            "demo_boot.1|Failed 8 seconds ago|task: non-zero exit (1)\n",
            churning=600,
        )
        self.assertEqual(proc.returncode, 1)

    def test_a_slot_that_burned_three_attempts_is_terminal(self) -> None:
        proc = self._run(
            "demo_flap 0/1\n",
            "demo_flap.1 desired=Running current=Starting error=\n",
            "demo_flap.1|Ready 1 second ago|\n"
            "demo_flap.1|Failed 2 seconds ago|task: non-zero exit (1)\n"
            "demo_flap.1|Failed 8 seconds ago|task: non-zero exit (1)\n"
            "demo_flap.1|Failed 14 seconds ago|task: non-zero exit (1)\n",
            churning=600,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("stuck: demo_flap", proc.stderr)

    def test_three_attempts_inside_the_grace_window_still_wait(self) -> None:
        proc = self._run(
            "demo_flap 0/1\n",
            "demo_flap.1 desired=Running current=Starting error=\n",
            "demo_flap.1|Ready 1 second ago|\n"
            "demo_flap.1|Failed 2 seconds ago|task: non-zero exit (1)\n"
            "demo_flap.1|Failed 8 seconds ago|task: non-zero exit (1)\n"
            "demo_flap.1|Failed 14 seconds ago|task: non-zero exit (1)\n",
        )
        self.assertEqual(proc.returncode, 1)

    def test_errors_below_a_finished_attempt_do_not_carry_over(self) -> None:
        proc = self._run(
            "demo_again 0/1\n",
            "demo_again.1 desired=Running current=Pending error=\n",
            "demo_again.1|Pending 1 second ago|\n"
            "demo_again.1|Shutdown 4 seconds ago|\n"
            "demo_again.1|Failed 9 seconds ago|task: non-zero exit (1)\n"
            "demo_again.1|Failed 15 seconds ago|task: non-zero exit (1)\n"
            "demo_again.1|Failed 21 seconds ago|task: non-zero exit (1)\n",
            churning=600,
        )
        self.assertEqual(proc.returncode, 1)

    def test_an_unreadable_deploy_epoch_keeps_the_caller_waiting(self) -> None:
        proc = self._run(
            "demo_flap 0/1\n",
            "demo_flap.1 desired=Running current=Starting error=\n",
            "demo_flap.1|Ready 1 second ago|\n"
            "demo_flap.1|Failed 2 seconds ago|task: non-zero exit (1)\n"
            "demo_flap.1|Failed 8 seconds ago|task: non-zero exit (1)\n"
            "demo_flap.1|Failed 14 seconds ago|task: non-zero exit (1)\n",
            updated_at="<no value>",
        )
        self.assertEqual(proc.returncode, 1)

    def test_a_missing_task_state_dump_is_not_echoed_as_a_blank_line(self) -> None:
        proc = self._run(
            "demo_slow 0/1\n",
            "demo_slow.1 desired=Running current=Preparing error=\n",
        )
        self.assertNotIn("\n    \n", proc.stderr)


if __name__ == "__main__":
    unittest.main()
