from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import shutil
import signal
import sys
import threading
import time
import unittest
import unittest.mock as mock
from pathlib import Path

from ._fake_provision import harness_directory, load
from ._fake_spawner import FakeSpawner

provision = load("provision")
opentofu = provision.opentofu
sandbox = provision.sandbox
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
with runner.task_directory() as task:
    runner.opentofu.tofu(task, {"HOME": str(runner.sandbox.home_of(task))}, "apply")
"""
SLOW_TOFU = """#!{python}
import os, pathlib, signal, subprocess, sys, time
signal.signal(signal.SIGINT, signal.SIG_IGN)
marks = pathlib.Path(os.environ["FAKE_TOFU_MARKS"])
plugin = 0
child = [sys.executable, "-c", "import time; time.sleep(60)"]
if os.environ["FAKE_TOFU_PLUGIN"] == "spawn":
    plugin = subprocess.Popen(child).pid
if os.environ["FAKE_TOFU_PLUGIN"] == "session":
    plugin = subprocess.Popen(child, start_new_session=True).pid
lock = marks / "state.tflock"
mode = os.environ["FAKE_TOFU_SIGINT"]
def interrupted(_signum, _frame):
    (marks / "sigint").write_text("received", encoding="utf-8")
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
if mode == "return":
    sys.exit(0)
if mode == "fail":
    sys.exit(1)
time.sleep(60)
"""


class TofuCase(unittest.TestCase):
    def setUp(self):
        self.root = harness_directory()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for signum in (signal.SIGALRM, signal.SIGTERM):
            self.addCleanup(signal.signal, signum, signal.getsignal(signum))
        self.addCleanup(signal.alarm, 0)
        patcher = mock.patch.object(provision.tempfile, "tempdir", str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake = self.bin / "tofu"
        fake.write_text(SLOW_TOFU.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)
        self.spawner = FakeSpawner(
            load("sandbox.spawner"),
            self.root / "sandboxes",
            self.root,
            fake,
            provision.OPENTOFU / "tofurc",
        )
        self.addCleanup(self.spawner.close)
        self.marks = self.root / "marks"
        self.marks.mkdir()
        self.ready = self.root / "ready"
        self.sigint = self.marks / "sigint"
        self.lock = self.marks / "state.tflock"
        self.task = None
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
                ignores it; ``return`` exits 0 and ``fail`` 1 once ready.

        Returns:
            The settings the fake spawner hands every later run after its
            admission, as the spawner refuses paths outside a run;
            ``self.plugin`` is ``spawn`` for a fake tofu with a plugin child
            that ignores SIGINT, ``session`` for a plugin child in a session
            of its own, ``none`` without.
        """
        settings = {
            "FAKE_TOFU_SIGINT": sigint,
            "FAKE_TOFU_READY": str(self.ready),
            "FAKE_TOFU_PLUGIN": self.plugin,
            "FAKE_TOFU_MARKS": str(self.marks),
        }
        self.spawner.extra |= settings
        return settings

    def tofu_in_sandbox(self):
        with provision.task_directory() as task:
            self.task = task
            home = {"HOME": str(sandbox.home_of(task))}
            return opentofu.tofu(task, home, "apply", capture=self.capture)

    def run_apply(self, sigint, grace):
        """Args:
            sigint: the SIGINT behaviour of :meth:`environment`.
            grace: the ``TOFU_GRACE`` of the run.

        Returns:
            ``(exit code, stderr)`` of :func:`provision.main` running ``tofu
            apply`` in a sandbox of its own, with its output captured if
            ``self.capture``, the code of its ``SystemExit`` after a
            ``SIGTERM``; every :meth:`when` helper has acted by then.
        """
        self.environment(sigint)
        stderr = io.StringIO()
        signal.signal(signal.SIGTERM, provision._terminate)
        with (
            mock.patch.object(provision.provider_env, "RUN_BUDGET", TEST_BUDGET),
            mock.patch.object(provision.provider_env, "TOFU_GRACE", grace),
            mock.patch.object(provision, "dispatch", lambda *_: self.tofu_in_sandbox()),
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
        text = self.ready.read_bytes().decode("utf-8")  # nocheck: cache-read tempdir
        return dict(zip(TOFU_REPORT, map(int, text.split()), strict=True))

    def alive(self, pid):
        """Args:
            pid: a process the run started.

        Returns:
            Whether it still runs :data:`READY_BOUND` seconds later at the
            latest; a zombie no parent reaped yet counts as ended.
        """
        stat = self.stat(pid)
        if stat is None:
            return False
        start = stat[1]
        deadline = time.monotonic() + READY_BOUND
        while self.running(pid, start) and time.monotonic() < deadline:
            time.sleep(READY_POLL)
        return self.running(pid, start)

    def assert_ended(self, pid, what):
        """Args:
        pid: a process the run must have ended; it gets
            :data:`READY_BOUND` seconds, and SIGKILL if it still runs with
            the start time it had here, so a reused pid is never killed.
        what: the process the failure names.
        """
        if self.alive(pid):
            os.kill(pid, signal.SIGKILL)
            self.fail(f"{what} outlived the run")

    def assert_tofu_ended(self):
        self.assert_ended(self.tofu_report()["pid"], "the fake tofu")

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
            stat_file = Path(f"/proc/{pid}/stat")
            text = stat_file.read_bytes().decode("utf-8")  # nocheck: cache-read proc
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
