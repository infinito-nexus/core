from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock as mock
from pathlib import Path

from ._fake_provision import load

provision = load("provision")
opentofu = provision.opentofu
TEST_BUDGET = dt.timedelta(hours=1)
READY_BOUND = 30
READY_POLL = 0.01
TOFU_REPORT = ("pid", "group", "parent", "plugin")
RUNNER = """
import importlib.util, os, pathlib, sys
python = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(python))
spec = importlib.util.spec_from_file_location("runner", python / "provision.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.opentofu.tofu(pathlib.Path(sys.argv[2]), dict(os.environ), "apply")
"""
SLOW_TOFU = """#!{python}
import os, pathlib, signal, subprocess, sys, time
signal.signal(signal.SIGINT, signal.SIG_IGN)
plugin = 0
if os.environ["FAKE_TOFU_PLUGIN"] == "spawn":
    plugin = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]).pid
lock = pathlib.Path.cwd() / "state.tflock"
mode = os.environ["FAKE_TOFU_SIGINT"]
def interrupted(_signum, _frame):
    (pathlib.Path.cwd() / "sigint").write_text("received", encoding="utf-8")
    if mode == "trap":
        lock.unlink(missing_ok=True)
        sys.exit(130)
signal.signal(signal.SIGINT, signal.SIG_IGN if mode == "ignore" else interrupted)
lock.write_text("held", encoding="utf-8")
ready = pathlib.Path(os.environ["FAKE_TOFU_READY"])
part = ready.with_name(ready.name + ".part")
part.write_text(
    "%d %d %d %d" % (os.getpid(), os.getpgrp(), os.getppid(), plugin), encoding="utf-8"
)
part.replace(ready)
time.sleep(60)
"""


class TestTofuBudget(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for signum in (signal.SIGALRM, signal.SIGTERM):
            self.addCleanup(signal.signal, signum, signal.getsignal(signum))
        self.addCleanup(signal.alarm, 0)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake = self.bin / "tofu"
        fake.write_text(SLOW_TOFU.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)
        self.task = self.root / "task"
        self.task.mkdir()
        self.ready = self.root / "ready"
        self.sigint = self.task / "sigint"
        self.helpers = []
        self.plugin = "none"
        self.capture = False

    def when(self, marker, action):
        """Args:
        marker: the file a helper thread waits for, at most
            :data:`READY_BOUND` seconds.
        action: what the thread does once it appeared, e.g. a
            :meth:`send`.
        """
        done = threading.Event()

        def run():
            deadline = time.monotonic() + READY_BOUND
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(READY_POLL)
            if marker.exists():
                done.set()
                action()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.helpers.append((marker, thread, done))

    @staticmethod
    def send(signum):
        """Args:
            signum: the signal to send.

        Returns:
            An action that sends ``signum`` to this process.
        """
        return lambda: os.kill(os.getpid(), signum)

    def environment(self, sigint):
        """Args:
            sigint: what the fake tofu does on SIGINT: ``trap`` releases its
                lock and exits, ``linger`` notes it and runs on, ``ignore``
                ignores it.

        Returns:
            The environment of the fake tofu; ``self.plugin`` is ``spawn``
            for one with a plugin child that ignores SIGINT, ``none`` without.
        """
        return {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "FAKE_TOFU_SIGINT": sigint,
            "FAKE_TOFU_READY": str(self.ready),
            "FAKE_TOFU_PLUGIN": self.plugin,
        }

    def run_apply(self, sigint, grace):
        """Args:
            sigint: the SIGINT behaviour of :meth:`environment`.
            grace: the ``TOFU_GRACE`` of the run.

        Returns:
            ``(exit code, stderr)`` of :func:`provision.main` running ``tofu
            apply``, with its output captured if ``self.capture``, the code of
            its ``SystemExit`` after a ``SIGTERM``; every :meth:`when` helper
            has acted by then.
        """
        env = self.environment(sigint)
        stderr = io.StringIO()
        signal.signal(signal.SIGTERM, provision._terminate)
        with (
            mock.patch.object(provision.provider_env, "RUN_BUDGET", TEST_BUDGET),
            mock.patch.object(provision.provider_env, "TOFU_GRACE", grace),
            mock.patch.object(
                provision,
                "dispatch",
                lambda *_: opentofu.tofu(self.task, env, "apply", capture=self.capture),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            try:
                code = provision.main(["provision.py", "provision"], {}, Path("/none"))
            except SystemExit as stop:
                code = stop.code
        for marker, thread, done in self.helpers:
            thread.join()
            self.assertTrue(done.is_set(), f"the fake tofu never wrote {marker.name}")
        return code, stderr.getvalue()

    def tofu_report(self):
        """Returns:
        ``pid``, process ``group``, ``parent`` and ``plugin`` pid (0 for
        none) the fake tofu reported once ready.
        """
        text = self.ready.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        return dict(zip(TOFU_REPORT, map(int, text.split()), strict=True))

    def assert_ended(self, pid, what):
        """Args:
        pid: a process the run must have ended; it gets
            :data:`READY_BOUND` seconds, and SIGKILL if it still runs with
            the start time it had here, so a reused pid is never killed.
        what: the process the failure names.
        """
        stat = self.stat(pid)
        if stat is None:
            return
        start = stat[1]
        deadline = time.monotonic() + READY_BOUND
        while self.running(pid, start) and time.monotonic() < deadline:
            time.sleep(READY_POLL)
        if self.running(pid, start):
            os.kill(pid, signal.SIGKILL)
            self.fail(f"{what} outlived the run")

    def assert_tofu_ended(self):
        self.assert_ended(self.tofu_report()["pid"], "the fake tofu")

    def test_a_budget_end_interrupts_tofu_which_releases_its_lock(self):
        self.when(self.ready, self.send(signal.SIGALRM))
        code, stderr = self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        self.assertEqual(code, 1)
        self.assertTrue((self.task / "sigint").is_file())
        self.assertFalse((self.task / "state.tflock").exists())
        self.assertIn(f"the run exceeded its time budget of {TEST_BUDGET}", stderr)
        self.assertIn("tofu apply stopped on SIGINT with exit code 130", stderr)
        self.assert_tofu_ended()

    def test_tofu_runs_in_the_process_group_its_supervisor_leads(self):
        self.when(self.ready, self.send(signal.SIGALRM))
        self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        report = self.tofu_report()
        self.assertEqual(report["group"], report["parent"])
        self.assertNotEqual(report["group"], os.getpgrp())
        self.assertNotEqual(report["parent"], os.getpid())

    def test_the_kill_after_the_grace_takes_the_plugins_of_tofu(self):
        self.plugin = "spawn"
        self.when(self.ready, self.send(signal.SIGALRM))
        code, stderr = self.run_apply("ignore", dt.timedelta(milliseconds=200))
        self.assert_ended(self.tofu_report()["plugin"], "the plugin of tofu")
        self.assertEqual(code, 1)
        self.assertIn("ignored SIGINT", stderr)

    def test_the_death_of_the_runner_takes_tofu_and_its_plugins(self):
        self.plugin = "spawn"
        runner = subprocess.Popen(
            [
                sys.executable,
                "-c",
                RUNNER,
                str(Path(provision.__file__).parent),
                str(self.task),
            ],
            env=self.environment("trap"),
        )
        self.addCleanup(runner.wait)
        deadline = time.monotonic() + READY_BOUND
        while not self.ready.exists() and time.monotonic() < deadline:
            time.sleep(READY_POLL)
        runner.kill()
        self.assertTrue(self.ready.exists(), "the fake tofu never got ready")
        report = self.tofu_report()
        self.assert_ended(report["plugin"], "the plugin of tofu")
        self.assert_ended(report["pid"], "the fake tofu")

    def test_a_plugin_outliving_tofu_ends_with_the_run(self):
        self.plugin = "spawn"
        self.when(self.ready, self.send(signal.SIGALRM))
        code, stderr = self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        self.assertEqual(code, 1)
        self.assertIn("tofu apply stopped on SIGINT with exit code 130", stderr)
        self.assert_ended(self.tofu_report()["plugin"], "the plugin of tofu")

    def kill_supervisor(self):
        os.kill(self.tofu_report()["parent"], signal.SIGKILL)

    def test_a_killed_supervisor_gives_tofu_the_grace_then_takes_its_group(self):
        self.plugin = "spawn"
        self.when(self.ready, self.kill_supervisor)
        code, stderr = self.run_apply("trap", dt.timedelta(seconds=1))
        self.assertEqual(code, 1)
        self.assertIn(f"tofu apply died with {-signal.SIGKILL}", stderr)
        self.assertIn("may miss resources and keep its lock", stderr)
        self.assertTrue(self.sigint.is_file())
        self.assertFalse((self.task / "state.tflock").exists())
        report = self.tofu_report()
        self.assert_ended(report["plugin"], "the plugin of tofu")
        self.assert_ended(report["pid"], "the fake tofu")

    def test_a_budget_end_after_the_supervisor_died_keeps_the_grace(self):
        self.capture = True

        def kill_supervisor_then_end_the_budget():
            self.kill_supervisor()
            os.kill(os.getpid(), signal.SIGALRM)

        self.when(self.ready, kill_supervisor_then_end_the_budget)
        code, stderr = self.run_apply("linger", dt.timedelta(seconds=1))
        self.assertEqual(code, 1)
        self.assertIn(f"the run exceeded its time budget of {TEST_BUDGET}", stderr)
        self.assertNotIn("stopped on SIGINT", stderr)
        self.assertIn("may miss resources and keep its lock", stderr)
        self.assertTrue(self.sigint.is_file())
        self.assert_tofu_ended()

    def test_the_group_kill_finds_the_supervisor_unreaped(self):
        killpg = os.killpg
        states = []

        def recorded(group, signum):
            if signum == signal.SIGKILL:
                states.append(self.stat(group))
            killpg(group, signum)

        self.when(self.ready, self.send(signal.SIGALRM))
        with mock.patch.object(opentofu.os, "killpg", recorded):
            self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        self.assertEqual([state and state[0] for state in states], ["Z"])
        self.assert_tofu_ended()

    @staticmethod
    def stat(pid):
        """Args:
            pid: a process id.

        Returns:
            ``(state, start time)``, fields 3 and 22 of ``/proc/<pid>/stat``,
            or ``None`` once no process has that id, also when it ends
            between the open and the read of that file.
        """
        try:
            text = Path(f"/proc/{pid}/stat").read_text(
                encoding="utf-8"
            )  # nocheck: cache-read procfs
        except (FileNotFoundError, ProcessLookupError):
            return None
        fields = text.rsplit(")", 1)[1].split()
        return fields[0], fields[19]

    def running(self, pid, start):
        """Args:
            pid: a process id.
            start: the start time of the process meant, from :meth:`stat`.

        Returns:
            Whether that process runs; a zombie no parent reaped yet counts as
            ended, and so does another process that reused ``pid``.
        """
        stat = self.stat(pid)
        return stat is not None and stat[0] != "Z" and stat[1] == start

    def test_negative_control_tofu_ignoring_sigint_is_killed_after_the_grace(self):
        grace = dt.timedelta(milliseconds=200)
        self.when(self.ready, self.send(signal.SIGALRM))
        code, stderr = self.run_apply("ignore", grace)
        self.assertEqual(code, 1)
        self.assertFalse((self.task / "sigint").exists())
        self.assertTrue((self.task / "state.tflock").is_file())
        self.assertIn(f"the run exceeded its time budget of {TEST_BUDGET}", stderr)
        self.assertIn(f"tofu apply ignored SIGINT for {grace} and was killed", stderr)
        self.assert_tofu_ended()

    def test_a_sigterm_interrupts_tofu_which_releases_its_lock(self):
        self.when(self.ready, self.send(signal.SIGTERM))
        code, _ = self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertTrue((self.task / "sigint").is_file())
        self.assertFalse((self.task / "state.tflock").exists())
        self.assert_tofu_ended()

    def test_negative_control_a_sigterm_kills_tofu_ignoring_sigint_after_the_grace(
        self,
    ):
        grace = dt.timedelta(milliseconds=200)
        self.when(self.ready, self.send(signal.SIGTERM))
        code, _ = self.run_apply("ignore", grace)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertFalse(self.sigint.exists())
        self.assertTrue((self.task / "state.tflock").is_file())
        self.assert_tofu_ended()

    def test_a_second_signal_in_the_grace_kills_tofu_at_once(self):
        self.when(self.ready, self.send(signal.SIGALRM))
        self.when(self.sigint, self.send(signal.SIGTERM))
        started = time.monotonic()
        code, _ = self.run_apply("linger", dt.timedelta(seconds=READY_BOUND))
        self.assertLess(time.monotonic() - started, READY_BOUND)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertTrue((self.task / "state.tflock").is_file())
        self.assert_tofu_ended()

    def test_a_stop_holds_the_budget_off_during_the_grace(self):
        armed = []
        self.when(self.ready, self.send(signal.SIGTERM))
        self.when(
            self.sigint,
            lambda: armed.append(signal.getitimer(signal.ITIMER_REAL)[0]),
        )
        code, _ = self.run_apply("linger", dt.timedelta(seconds=1))
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertEqual(armed, [0.0])
        self.assert_tofu_ended()


if __name__ == "__main__":
    unittest.main()
