import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text

SCRIPT = PROJECT_ROOT / "roles/sys-svc-container/files/reconcile_runtime.sh"

SYSTEMCTL_STUB = """#!/bin/sh
echo "systemctl $*" >>"$STUB_LOG"
listed() { printf '%s\\n' "$2" | grep -qxF "$1"; }
case "$1" in
show)
\tvalue="$(grep -E "^$4 " "$STUB_TIMES" | awk '{print $2}')"
\techo "${value:-0}"
\t;;
list-units)
\tshift
\tpattern=""
\twant_active=0
\tfor arg in "$@"; do
\t\tcase "$arg" in
\t\t--state=active) want_active=1 ;;
\t\t--*) ;;
\t\t*) pattern="$arg" ;;
\t\tesac
\tdone
\tfor unit in $STUB_SCOPES; do
\t\tcase "$unit" in
\t\t$pattern) ;;
\t\t*) continue ;;
\t\tesac
\t\tif [ "$want_active" -eq 1 ] && listed "$unit" "$STUB_INACTIVE"; then
\t\t\tcontinue
\t\tfi
\t\techo "$unit"
\tdone
\t;;
stop)
\tshift
\tfor unit in "$@"; do
\t\tlisted "$unit" "$STUB_STOP_RC5" && exit 5
\t\tlisted "$unit" "$STUB_STOP_FAIL" && exit 1
\t\tlisted "$unit" "$STUB_STOP_TIMEOUT" && exit 124
\t\techo "$unit" >>"$STUB_STOPPED"
\tdone
\t;;
restart)
\tlisted "$2" "$STUB_RESTART_FAIL" && exit 1
\t;;
is-active)
\tif [ "$2" = docker.service ]; then
\t\techo "$STUB_DOCKER_STATE"
\t\texit 0
\tfi
\tlisted "$2" "$STUB_STICKY" && { echo active; exit 0; }
\tif grep -qxF "$2" "$STUB_STOPPED" 2>/dev/null; then
\t\techo inactive
\t\texit 3
\tfi
\techo active
\t;;
esac
exit 0
"""


class TestReconcileRuntime(unittest.TestCase):
    def run_script(
        self,
        *,
        times,
        scopes,
        inactive=(),
        stop_rc5=(),
        stop_fail=(),
        stop_timeout=(),
        sticky=(),
        restart_fail=(),
        docker_state="active",
    ):
        """Run the script against a stubbed systemctl.

        Args:
            times: unit name -> ActiveEnterTimestampMonotonic. Units left out
                answer 0, which is what systemd reports for a unit it no
                longer knows.
            scopes: unit names systemd knows, filtered by the glob and the
                state selector the script passes to `list-units`.
            inactive: the subset of scopes that are not active.
            stop_rc5: units whose stop exits 5, systemd's "no such unit".
            stop_fail: units whose stop exits 1.
            stop_timeout: units whose stop exits 124, what timeout(1) returns
                when it kills the call.
            sticky: units that keep reporting active after being stopped.
            restart_fail: units whose restart exits 1.
            docker_state: what `systemctl is-active docker.service` answers.

        Returns:
            Tuple of exit code, combined output and the recorded invocations.
        """
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            log = bin_dir / "calls.log"
            times_file = bin_dir / "times"
            times_file.write_text(
                "".join(f"{unit} {value}\n" for unit, value in times.items())
            )
            stub = bin_dir / "systemctl"
            stub.write_text(SYSTEMCTL_STUB)
            stub.chmod(0o755)
            no_sleep = bin_dir / "sleep"
            no_sleep.write_text("#!/bin/sh\nexit 0\n")
            no_sleep.chmod(0o755)
            env = dict(os.environ)
            env.update(
                PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
                STUB_LOG=str(log),
                STUB_TIMES=str(times_file),
                STUB_STOPPED=str(bin_dir / "stopped"),
                STUB_SCOPES=" ".join(scopes),
                STUB_INACTIVE="\n".join(inactive),
                STUB_STOP_RC5="\n".join(stop_rc5),
                STUB_STOP_FAIL="\n".join(stop_fail),
                STUB_STOP_TIMEOUT="\n".join(stop_timeout),
                STUB_STICKY="\n".join(sticky),
                STUB_RESTART_FAIL="\n".join(restart_fail),
                STUB_DOCKER_STATE=docker_state,
            )
            done = subprocess.run(
                ["bash", str(SCRIPT)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            calls = read_text(str(log)) if log.exists() else ""
            return done.returncode, done.stdout + done.stderr, calls

    def test_healthy_node_changes_nothing(self):
        code, out, calls = self.run_script(
            times={"containerd.service": 100, "docker-any.scope": 300},
            scopes=["docker-any.scope"],
        )
        self.assertEqual(code, 0)
        self.assertIn("UNCHANGED", out)
        self.assertNotIn("systemctl stop", calls)
        self.assertNotIn("systemctl restart", calls)

    def test_without_a_running_containerd_it_does_nothing(self):
        code, out, calls = self.run_script(times={}, scopes=["docker-any.scope"])
        self.assertEqual(code, 0)
        self.assertIn("no running containerd", out)
        self.assertNotIn("systemctl stop", calls)

    def test_scope_older_than_the_restarted_containerd_is_reaped(self):
        code, out, calls = self.run_script(
            times={
                "containerd.service": 300,
                "docker-orphan.scope": 150,
                "docker-fresh.scope": 400,
            },
            scopes=["docker-orphan.scope", "docker-fresh.scope"],
        )
        self.assertEqual(code, 0)
        self.assertIn("RECONCILED: 1 orphaned container scope(s)", out)
        self.assertIn("systemctl stop docker-orphan.scope", calls)
        self.assertNotIn("stop docker-fresh.scope", calls)
        self.assertIn("systemctl restart docker.service", calls)
        self.assertNotIn("--no-block", calls)

    def test_an_inactive_scope_is_left_alone(self):
        code, out, calls = self.run_script(
            times={
                "containerd.service": 300,
                "docker-dead.scope": 150,
                "docker-orphan.scope": 150,
            },
            scopes=["docker-dead.scope", "docker-orphan.scope"],
            inactive=["docker-dead.scope"],
        )
        self.assertEqual(code, 0)
        self.assertIn("RECONCILED: 1 orphaned container scope(s)", out)
        self.assertNotIn("stop docker-dead.scope", calls)

    def test_units_outside_the_docker_scope_namespace_are_left_alone(self):
        code, out, calls = self.run_script(
            times={
                "containerd.service": 300,
                "sshd.service": 150,
                "docker-orphan.scope": 150,
            },
            scopes=["sshd.service", "docker-orphan.scope"],
        )
        self.assertEqual(code, 0)
        self.assertIn("RECONCILED: 1 orphaned container scope(s)", out)
        self.assertNotIn("stop sshd.service", calls)

    def test_a_vanished_unit_is_not_mistaken_for_an_orphan(self):
        """systemd answers 0 for a unit it no longer knows, and 0 would sort
        before every real timestamp."""
        code, out, calls = self.run_script(
            times={"containerd.service": 300},
            scopes=["docker-gone.scope"],
        )
        self.assertEqual(code, 0)
        self.assertIn("UNCHANGED", out)
        self.assertNotIn("systemctl stop", calls)

    def test_a_scope_that_stops_itself_mid_run_is_tolerated(self):
        code, out, calls = self.run_script(
            times={"containerd.service": 300, "docker-racing.scope": 150},
            scopes=["docker-racing.scope"],
            stop_rc5=["docker-racing.scope"],
        )
        self.assertEqual(code, 0)
        self.assertIn("UNCHANGED", out)
        self.assertNotIn("systemctl restart", calls)

    def test_a_failing_stop_aborts_instead_of_restarting_dockerd(self):
        code, out, calls = self.run_script(
            times={"containerd.service": 300, "docker-stuck.scope": 150},
            scopes=["docker-stuck.scope"],
            stop_fail=["docker-stuck.scope"],
        )
        self.assertEqual(code, 1)
        self.assertIn("could not stop docker-stuck.scope", out)
        self.assertNotIn("systemctl restart", calls)

    def test_a_stop_that_outlasts_the_timeout_aborts(self):
        code, out, calls = self.run_script(
            times={"containerd.service": 300, "docker-wedged.scope": 150},
            scopes=["docker-wedged.scope"],
            stop_timeout=["docker-wedged.scope"],
        )
        self.assertEqual(code, 1)
        self.assertIn("rc 124", out)
        self.assertNotIn("systemctl restart", calls)

    def test_a_scope_surviving_its_stop_aborts(self):
        code, out, calls = self.run_script(
            times={"containerd.service": 300, "docker-undead.scope": 150},
            scopes=["docker-undead.scope"],
            sticky=["docker-undead.scope"],
        )
        self.assertEqual(code, 1)
        self.assertIn("still active after being stopped", out)
        self.assertNotIn("systemctl restart", calls)

    def test_a_dockerd_that_does_not_come_back_aborts(self):
        code, out, _ = self.run_script(
            times={"containerd.service": 300, "docker-orphan.scope": 150},
            scopes=["docker-orphan.scope"],
            docker_state="failed",
        )
        self.assertEqual(code, 1)
        self.assertIn("cannot start containers", out)

    def test_a_slow_restart_that_still_comes_up_is_not_a_failure(self):
        code, out, _ = self.run_script(
            times={"containerd.service": 300, "docker-orphan.scope": 150},
            scopes=["docker-orphan.scope"],
            restart_fail=["docker.service"],
        )
        self.assertEqual(code, 0)
        self.assertIn("RECONCILED: 1 orphaned container scope(s)", out)


if __name__ == "__main__":
    unittest.main()
