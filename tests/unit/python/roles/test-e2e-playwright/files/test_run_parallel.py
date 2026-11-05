import fcntl
import importlib.util
import itertools
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from . import PROJECT_ROOT


def _load_module():
    path = PROJECT_ROOT / "roles" / "test-e2e-playwright" / "files" / "run_parallel.py"
    spec = importlib.util.spec_from_file_location("playwright_run_parallel", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["playwright_run_parallel"] = module
    spec.loader.exec_module(module)
    return module


rp = _load_module()

ROW = [
    ("web-app-keycloak", 118),
    ("web-app-hermes", 50),
    ("web-app-matomo", 165),
    ("web-app-openclaw", 29),
    ("web-app-weblate", 84),
    ("web-svc-cdn", 8),
    ("web-svc-design", 85),
    ("web-svc-logout", 76),
    ("web-svc-mirror", 7),
    ("web-svc-simpleicons", 8),
    ("web-svc-translate", 20),
    ("web-app-dashboard", 247),
    ("web-app-discourse", 224),
    ("web-app-stalwart", 162),
    ("web-app-jitsi", 65),
    ("web-app-matrix", 449),
    ("web-app-prometheus", 39),
    ("web-app-wordpress", 182),
]


def simulate(jobs, cap, release=None):
    """Drive a Plan on a virtual clock.

    Args:
        jobs: ``(Job, seconds)`` in submission order.
        cap: the plan's concurrency cap.
        release: per job id, the virtual second its file appears; 0 when absent.

    Returns:
        ``(starts, ends, peak)``: per job id its start and end second, and the
        most jobs that ever ran at once.
    """
    release = release or {}
    plan = rp.Plan(cap)
    durations = {job.id: seconds for job, seconds in jobs}
    queue = list(jobs)
    starts, ends, running = {}, {}, {}
    now, peak = 0.0, 0
    while True:
        while queue and release.get(queue[0][0].id, 0) <= now:
            plan.submit(queue.pop(0)[0])
        if not queue:
            plan.seal()
        for job in plan.start_next():
            starts[job.id] = now
            running[job.id] = now + durations[job.id]
        peak = max(peak, len(running))
        if plan.done():
            return starts, ends, peak
        events = list(running.values()) + (
            [release.get(queue[0][0].id, 0)] if queue else []
        )
        now = min(event for event in events if event >= now)
        for job_id, end in list(running.items()):
            if end <= now:
                del running[job_id]
                ends[job_id] = end
                plan.finish(job_id)


def row_jobs():
    head = ROW[0][0]
    return [
        (rp.Job(app, () if app == head else (head,)), seconds) for app, seconds in ROW
    ]


class TestPlan(unittest.TestCase):
    def test_the_cap_is_never_exceeded(self):
        for cap in (1, 2, 3, 4):
            with self.subTest(cap=cap):
                _, _, peak = simulate(row_jobs(), cap)
                self.assertLessEqual(peak, cap)

    def test_cap_one_reproduces_the_serial_order(self):
        starts, ends, _ = simulate(row_jobs(), 1)
        order = sorted(starts, key=starts.get)
        self.assertEqual(order, [app for app, _ in ROW])
        for previous, following in itertools.pairwise(order):
            self.assertLessEqual(ends[previous], starts[following])

    def test_no_job_starts_before_the_jobs_it_runs_after(self):
        jobs = row_jobs()
        jobs[13] = (
            rp.Job("web-app-stalwart", ("web-app-keycloak", "web-app-matomo")),
            162,
        )
        starts, ends, _ = simulate(jobs, 3)
        for job, _ in jobs:
            for dep in job.after:
                self.assertGreaterEqual(
                    starts[job.id], ends[dep], f"{job.id} started before {dep} ended"
                )

    def test_the_identity_provider_runs_alone_first(self):
        starts, ends, _ = simulate(row_jobs(), 3)
        head = ROW[0][0]
        self.assertEqual(starts[head], 0)
        self.assertTrue(all(starts[app] >= ends[head] for app, _ in ROW[1:]))

    def test_every_job_runs_exactly_once(self):
        starts, ends, _ = simulate(row_jobs(), 3)
        self.assertEqual(set(starts), {app for app, _ in ROW})
        self.assertEqual(set(ends), set(starts))

    def test_a_dependency_that_is_not_submitted_yet_holds_the_job(self):
        plan = rp.Plan(3)
        plan.submit(rp.Job("b", ("a",)))
        self.assertEqual(plan.start_next(), [])
        plan.submit(rp.Job("a", ()))
        self.assertEqual([job.id for job in plan.start_next()], ["a"])

    def test_a_dependency_that_never_ran_defers_its_dependents_transitively(self):
        plan = rp.Plan(3)
        plan.submit(rp.Job("b", ("dropped",)))
        plan.submit(rp.Job("c", ("b",)))
        plan.submit(rp.Job("d", ()))
        plan.seal()
        self.assertEqual([job.id for job in plan.start_next()], ["d"])
        self.assertEqual([job.id for job in plan.defer_orphans()], ["b", "c"])
        plan.finish("d")
        self.assertTrue(plan.done())

    def test_a_ready_job_overtakes_a_blocked_one_but_keeps_submission_order(self):
        plan = rp.Plan(2)
        plan.submit(rp.Job("a", ()))
        plan.submit(rp.Job("b", ("a",)))
        plan.submit(rp.Job("c", ()))
        plan.submit(rp.Job("d", ()))
        self.assertEqual([job.id for job in plan.start_next()], ["a", "c"])

    def test_an_unsatisfiable_sealed_list_raises(self):
        plan = rp.Plan(2)
        plan.submit(rp.Job("a", ("b",)))
        plan.submit(rp.Job("b", ("a",)))
        plan.seal()
        self.assertEqual(plan.start_next(), [])
        with self.assertRaises(RuntimeError):
            plan.defer_orphans()

    def test_a_duplicate_submission_raises(self):
        plan = rp.Plan(2)
        plan.submit(rp.Job("a", ()))
        with self.assertRaises(ValueError):
            plan.submit(rp.Job("a", ()))

    def test_a_cap_below_one_raises(self):
        with self.assertRaises(ValueError):
            rp.Plan(0)

    def test_the_measured_row_drains_well_inside_the_serial_time(self):
        setup = 27
        release = {app: setup * (index + 1) for index, (app, _) in enumerate(ROW)}
        _, ends, _ = simulate(row_jobs(), 3, release)
        serial = sum(seconds + setup for _, seconds in ROW)
        self.assertEqual(serial, 2504)
        self.assertEqual(max(ends.values()), 1020)


class FakeHost:
    """Pressure and meminfo files a test rewrites at will.

    Args:
        root: directory for the two files.
    """

    def __init__(self, root: Path) -> None:
        self.pressure = root / "pressure"
        self.meminfo = root / "meminfo"
        self.now = 0.0
        self.set(cpu_avg10=5.0, mem_available_mb=8192)

    def set(
        self, *, cpu_avg10: float, mem_available_mb: int, cpu_avg60: float = 1.0
    ) -> None:
        self.pressure.write_text(
            f"some avg10={cpu_avg10:.2f} avg60={cpu_avg60:.2f} avg300=1.00 total=1\n"
            "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
        )
        self.meminfo.write_text(
            f"MemTotal: 16000000 kB\nMemAvailable: {mem_available_mb * 1024} kB\n"
        )

    def gate(self, sustain: float = 0.0, clock=time.monotonic) -> "rp.HostGate":
        return rp.HostGate(36.0, 0.5, sustain, self.pressure, self.meminfo, clock)


class TestHostGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="host_gate_")
        self.addCleanup(self.tmp.cleanup)
        self.host = FakeHost(Path(self.tmp.name))
        self.clock = [0.0]
        self.gate = self.host.gate(sustain=30.0, clock=lambda: self.clock[0])

    def _samples(self, seconds, **load):
        self.host.set(**load)
        for _ in range(seconds):
            self.gate.observe()
            self.clock[0] += 1.0

    def test_the_first_container_always_starts(self):
        self.host.set(cpu_avg10=99.0, cpu_avg60=99.0, mem_available_mb=10)
        self.gate.observe()
        self.assertTrue(self.gate.admits(0, 1536))

    def test_a_further_container_needs_a_full_calm_window(self):
        self._samples(29, cpu_avg10=5.0, mem_available_mb=8192)
        self.assertFalse(self.gate.admits(1, 1536))
        self._samples(2, cpu_avg10=5.0, mem_available_mb=8192)
        self.assertTrue(self.gate.admits(1, 1536))

    def test_a_single_dip_in_avg10_does_not_admit(self):
        self._samples(60, cpu_avg10=50.0, cpu_avg60=50.0, mem_available_mb=8192)
        self._samples(1, cpu_avg10=10.0, cpu_avg60=50.0, mem_available_mb=8192)
        self.assertFalse(self.gate.admits(1, 1536))
        self._samples(40, cpu_avg10=10.0, cpu_avg60=50.0, mem_available_mb=8192)
        self.assertFalse(self.gate.admits(1, 1536))

    def test_one_hot_sample_restarts_the_window(self):
        self._samples(25, cpu_avg10=5.0, mem_available_mb=8192)
        self._samples(1, cpu_avg10=36.5, mem_available_mb=8192)
        self._samples(25, cpu_avg10=5.0, mem_available_mb=8192)
        self.assertFalse(self.gate.admits(1, 1536))
        self._samples(6, cpu_avg10=5.0, mem_available_mb=8192)
        self.assertTrue(self.gate.admits(1, 1536))

    def test_a_start_restarts_the_window(self):
        self._samples(31, cpu_avg10=5.0, mem_available_mb=8192)
        self.assertTrue(self.gate.admits(1, 1536))
        self.assertFalse(self.gate.admits(2, 1536))
        self._samples(31, cpu_avg10=5.0, mem_available_mb=8192)
        self.assertTrue(self.gate.admits(2, 1536))

    def test_an_estimate_above_half_the_free_memory_holds_the_next_container(self):
        self._samples(31, cpu_avg10=5.0, mem_available_mb=3071)
        self.assertFalse(self.gate.admits(1, 1536))
        self._samples(1, cpu_avg10=5.0, mem_available_mb=3072)
        self.assertTrue(self.gate.admits(1, 1536))

    def test_an_unreadable_host_keeps_the_round_serial(self):
        self.host.pressure.unlink()
        for _ in range(60):
            self.gate.observe()
            self.clock[0] += 1.0
        self.assertFalse(self.gate.admits(1, 1536))
        self.assertTrue(self.gate.admits(0, 1536))


class TestRun(unittest.TestCase):
    SCHEDULER = (
        PROJECT_ROOT / "roles" / "test-e2e-playwright" / "files" / "run_parallel.py"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="run_parallel_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.jobs = self.root / "jobs"
        self.jobs.mkdir()
        self.trace = self.root / "trace.log"
        self.host = FakeHost(self.root)
        self.tor_lock = self.root / "tor.lock"

    def _job(
        self,
        index,
        job_id,
        seconds,
        *,
        rc=0,
        after=(),
        timeout=60,
        tor=False,
        name=None,
    ):
        script = (
            "import sys,time;"
            f"open({str(self.trace)!r},'a').write('start {job_id} %f\\n' % time.time());"
            f"time.sleep({seconds});"
            f"open({str(self.trace)!r},'a').write('end {job_id} %f\\n' % time.time());"
            f"print('out-{job_id}');print('err-{job_id}',file=sys.stderr);sys.exit({rc})"
        )
        spec = {
            "id": job_id,
            "argv": [sys.executable, "-c", script],
            "env": {"PLAYWRIGHT_TEST_MARKER": job_id},
            "timeout": timeout,
            "after": list(after),
            "tor": tor,
            "workers": 1,
            "memory_mb": 1536,
            "stop": [
                sys.executable,
                "-c",
                f"open({str(self.root / ('stopped-' + job_id))!r},'w').write('x')",
            ],
            "meta": {"reports_dir": f"/reports/{job_id}"},
        }
        (self.jobs / (name or f"{index}-{job_id}.job.json")).write_text(
            json.dumps(spec)
        )

    def _run(self, cap, poll=0.05, onion_cap=3):
        return rp.run(
            self.jobs,
            cap,
            poll,
            self.host.gate(),
            rp.TorReaders(self.tor_lock, onion_cap),
        )

    def _result(self, job_id):
        text = (self.jobs / f"{job_id}.result.json").read_text()  # nocheck: cache-read
        return json.loads(text)

    def _trace(self):
        text = self.trace.read_text()  # nocheck: cache-read
        return [line.split() for line in text.splitlines()]

    def _stamps(self, kind, job_id):
        return [
            float(stamp)
            for event, name, stamp in self._trace()
            if [event, name] == [kind, job_id]
        ]

    def _peak(self):
        live, peak = 0, 0
        events = sorted(
            (float(stamp), 1 if kind == "start" else -1)
            for kind, _, stamp in self._trace()
        )
        for _, delta in events:
            live += delta
            peak = max(peak, live)
        return peak

    def test_jobs_run_concurrently_within_the_cap_and_keep_their_own_results(self):
        self._job(0, "head", 0.3)
        for index, name in enumerate(["a", "b", "c", "d"], start=1):
            self._job(index, name, 0.6, rc=1 if name == "b" else 0, after=["head"])
        (self.jobs / rp.SEALED).touch()
        began = time.monotonic()
        self.assertEqual(self._run(2), 0)
        elapsed = time.monotonic() - began
        self.assertEqual(self._peak(), 2)
        self.assertLess(elapsed, 0.3 + 4 * 0.6)
        self.assertEqual(self._result("b")["rc"], 1)
        for name in ("head", "a", "c", "d"):
            self.assertEqual(self._result(name)["rc"], 0)
            self.assertEqual(self._result(name)["stdout"].strip(), f"out-{name}")
            self.assertEqual(self._result(name)["stderr"].strip(), f"err-{name}")
            self.assertEqual(
                self._result(name)["meta"], {"reports_dir": f"/reports/{name}"}
            )
        head_end = self._stamps("end", "head")[0]
        for name in ("a", "b", "c", "d"):
            self.assertGreaterEqual(self._stamps("start", name)[0], head_end)

    def test_a_hot_host_runs_the_round_serially(self):
        self.host.set(cpu_avg10=80.0, mem_available_mb=8192)
        for index, name in enumerate(["a", "b", "c"]):
            self._job(index, name, 0.2)
        (self.jobs / rp.SEALED).touch()
        self.assertEqual(self._run(3), 0)
        self.assertEqual(self._peak(), 1)

    def test_a_timeout_kills_only_its_own_job_and_says_so_in_stderr(self):
        self._job(0, "slow", 30, timeout=0.5)
        self._job(1, "fast", 0.2)
        (self.jobs / rp.SEALED).touch()
        self.assertEqual(self._run(2), 0)
        slow = self._result("slow")
        self.assertTrue(slow["timed_out"])
        self.assertNotIn("rc", slow)
        self.assertIn("timeout", slow["msg"])
        self.assertIn(slow["msg"], slow["stderr"])
        self.assertTrue((self.root / "stopped-slow").exists())
        self.assertEqual(self._result("fast")["rc"], 0)

    def test_jobs_streamed_before_the_seal_are_all_run(self):
        self._job(0, "first", 0.2)
        runner = threading.Thread(target=self._run, args=(3,))
        runner.start()
        time.sleep(0.4)
        self._job(1, "second", 0.1)
        (self.jobs / rp.SEALED).touch()
        runner.join(timeout=10)
        self.assertFalse(runner.is_alive())
        self.assertEqual(self._result("first")["rc"], 0)
        self.assertEqual(self._result("second")["rc"], 0)

    def test_the_temp_file_ansible_copy_writes_is_ignored(self):
        self._job(0, "a", 0.1)
        self._job(1, "b", 0.1, name=".ansible_tmpk3j2x11-b.job.json")
        (self.jobs / ".ansible_tmpq9z").write_text("{")
        (self.jobs / rp.SEALED).touch()
        self.assertEqual(self._run(2), 0)
        self.assertEqual(self._result("a")["rc"], 0)
        self.assertFalse((self.jobs / "b.result.json").exists())

    def test_a_freed_slot_is_refilled_without_waiting_a_poll(self):
        self._job(0, "a", 0.2)
        self._job(1, "b", 0.1, after=["a"])
        (self.jobs / rp.SEALED).touch()
        self.assertEqual(self._run(1, poll=1.0), 0)
        self.assertLess(
            self._stamps("start", "b")[0] - self._stamps("end", "a")[0], 0.6
        )

    def test_a_scheduler_crash_stops_every_running_container(self):
        self._job(0, "long", 30)
        runner_error = []

        def drive():
            try:
                self._run(2)
            except Exception as exc:
                runner_error.append(exc)

        runner = threading.Thread(target=drive)
        runner.start()
        deadline = time.monotonic() + 5
        while not self.trace.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        (self.jobs / "1-broken.job.json").write_text("{not json")
        runner.join(timeout=30)
        self.assertFalse(runner.is_alive())
        self.assertEqual(len(runner_error), 1)
        self.assertTrue((self.root / "stopped-long").exists())
        self.assertEqual(self._stamps("end", "long"), [])

    def _scheduler(self) -> subprocess.Popen:
        return subprocess.Popen(
            [
                sys.executable,
                str(self.SCHEDULER),
                str(self.jobs),
                "2",
                "0.05",
                "36",
                "0.5",
                "0",
                str(self.tor_lock),
                "3",
            ],
            env=os.environ.copy(),
        )

    def test_a_marker_a_killed_probe_left_in_an_earlier_round_does_not_hold_onion_runs(
        self,
    ):
        self.tor_lock.with_name(self.tor_lock.name + ".recreate-pending").touch()
        self._job(0, "onion", 0.1, tor=True)
        (self.jobs / rp.SEALED).touch()
        proc = self._scheduler()
        try:
            self.assertEqual(proc.wait(timeout=10), 0)
        finally:
            proc.kill()
        self.assertEqual(self._result("onion")["rc"], 0)

    def test_sigterm_to_the_scheduler_stops_its_containers(self):
        self._job(0, "long", 30)
        proc = self._scheduler()
        deadline = time.monotonic() + 10
        while not self.trace.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertTrue((self.root / "stopped-long").exists())

    def test_an_onion_job_waits_while_tor_is_being_recreated(self):
        self._job(0, "onion", 0.1, tor=True)
        self._job(1, "clear", 0.1)
        writer = os.open(self.tor_lock, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(writer, fcntl.LOCK_EX)
        (self.jobs / rp.SEALED).touch()
        runner = threading.Thread(target=self._run, args=(2,))
        runner.start()
        time.sleep(0.6)
        self.assertEqual(self._stamps("start", "onion"), [])
        self.assertEqual(len(self._stamps("end", "clear")), 1)
        released = time.time()
        fcntl.flock(writer, fcntl.LOCK_UN)
        os.close(writer)
        runner.join(timeout=10)
        self.assertGreaterEqual(self._stamps("start", "onion")[0], released)

    def test_onion_jobs_share_tor_with_each_other(self):
        self._job(0, "onion-a", 0.5, tor=True)
        self._job(1, "onion-b", 0.5, tor=True)
        (self.jobs / rp.SEALED).touch()
        self.assertEqual(self._run(2), 0)
        self.assertEqual(self._peak(), 2)

    def test_onion_jobs_stay_within_the_tor_cap(self):
        for index, name in enumerate(["onion-a", "onion-b", "onion-c"]):
            self._job(index, name, 0.4, tor=True)
        self._job(3, "clear", 0.4)
        (self.jobs / rp.SEALED).touch()
        self.assertEqual(self._run(4, onion_cap=1), 0)
        onion = sorted(
            (self._stamps("start", name)[0], self._stamps("end", name)[0])
            for name in ("onion-a", "onion-b", "onion-c")
        )
        for (_, previous_end), (next_start, _) in itertools.pairwise(onion):
            self.assertGreaterEqual(next_start, previous_end)
        self.assertLess(self._stamps("start", "clear")[0], onion[0][1])

    def test_a_dropped_identity_provider_runs_none_of_its_dependents_here(self):
        head = "web-app-keycloak"
        self._job(1, "a", 0.1, after=[head])
        self._job(2, "b", 0.1, after=[head])
        self._job(3, "c", 0.1, after=[head, "b"])
        (self.jobs / rp.SEALED).touch()
        self.assertEqual(self._run(3), 0)
        self.assertFalse(self.trace.exists())
        self.assertEqual(self._result("a")["deferred"], [head])
        self.assertEqual(self._result("c")["deferred"], [head, "b"])
        self.assertNotIn("rc", self._result("b"))

    def test_no_onion_job_starts_while_a_recreate_is_pending(self):
        self._job(0, "onion", 0.1, tor=True)
        pending = self.tor_lock.with_name(self.tor_lock.name + ".recreate-pending")
        pending.touch()
        (self.jobs / rp.SEALED).touch()
        runner = threading.Thread(target=self._run, args=(2,))
        runner.start()
        time.sleep(0.5)
        self.assertFalse(self.trace.exists())
        cleared = time.time()
        pending.unlink()
        runner.join(timeout=10)
        self.assertGreaterEqual(self._stamps("start", "onion")[0], cleared)


class TestTorReaders(unittest.TestCase):
    def test_the_lock_it_creates_is_open_to_its_owner_only_whatever_the_umask(self):
        tmp = tempfile.TemporaryDirectory(prefix="tor_readers_")
        self.addCleanup(tmp.cleanup)
        lock = Path(tmp.name) / "tor.lock"
        readers = rp.TorReaders(lock, 1)
        self.addCleanup(os.umask, os.umask(0))
        self.assertTrue(readers.acquire("onion", 1))
        readers.release("onion")
        self.assertEqual(0o600, stat.S_IMODE(lock.stat().st_mode))


class TestRunSignals(unittest.TestCase):
    def test_retries_flaky_tests_and_crashed_pages_are_counted(self):
        output = (
            "  ✘  3 tests/a.js:1:1 › login (retry #1) (2.1m)\n"
            "  ✓  4 tests/a.js:1:1 › login (retry #2) (1.0m)\n"
            "Error: page.goto: Page crashed\n"
            "  1 flaky\n"
            "  12 passed (9.0m)\n"
        )
        self.assertEqual(
            rp.run_signals(output),
            {"retries": 2, "flaky": 1, "crashes": 1, "crash_kinds": "page crashed 1"},
        )

    def test_a_killed_browser_or_worker_that_a_retry_hid_is_still_named(self):
        output = (
            "  ✘  1 tests/a.js:1:1 › login (2.1m)\n"
            "Error: browserType.launch: Browser closed.\n"
            "Error: page.click: Target page, context or browser has been closed\n"
            "Error: worker process exited unexpectedly (code=null, signal=SIGKILL)\n"
            "  ✓  2 tests/a.js:1:1 › login (retry #1) (1.0m)\n"
            "  1 flaky\n"
        )
        self.assertEqual(
            rp.run_signals(output),
            {
                "retries": 1,
                "flaky": 1,
                "crashes": 3,
                "crash_kinds": "browser closed (OOM or timeout) 2, worker killed 1",
            },
        )

    def test_a_clean_run_reports_nothing(self):
        self.assertEqual(
            rp.run_signals("  12 passed (9.0m)\n"),
            {"retries": 0, "flaky": 0, "crashes": 0, "crash_kinds": ""},
        )


class TestTorRecreateWaitsForOnionRuns(unittest.TestCase):
    """The probe script recreates Tor only once no onion run holds the lock."""

    SCRIPT = (
        PROJECT_ROOT
        / "roles"
        / "test-e2e-playwright"
        / "files"
        / "wait_onion_reachable.sh"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tor_lock_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.marker = self.root / "recreated"
        self.answers = self.root / "onion-answers"
        self.lock = self.root / "tor.lock"
        self.pending = self.root / "tor.lock.recreate-pending"
        (self.bin / "curl").write_text(
            f"#!/bin/sh\nif [ -e {self.answers} ]; then printf 200; exit 0; fi\nexit 7\n"
        )
        (self.bin / "docker").write_text(
            "#!/bin/sh\n"
            f"if [ \"$2\" = update ]; then python3 -c \"import time; open('{self.marker}','w').write(str(time.time()))\"; fi\n"
            "exit 0\n"
        )
        for stub in ("curl", "docker"):
            (self.bin / stub).chmod(0o755)

    def start(self, script: Path, lock: str) -> subprocess.Popen:
        """Start *script* with one attempt, a 2 s delay and a 1 s max time.

        Args:
            script: the probe script under test.
            lock: the Tor lock argument, empty for the serial run.

        Returns:
            The running script.
        """
        return subprocess.Popen(
            [
                "bash",
                str(script),
                "127.0.0.1:9050",
                "x.onion",
                "1",
                "2",
                "1",
                str(self.root),
                lock,
            ],
            env={**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def run_script(
        self, script: Path, hold: float, answer_at: float | None = None
    ) -> tuple[float | None, int, str, bool]:
        """Run *script* in the parallel mode while a reader holds the Tor lock.

        Args:
            script: the probe script under test.
            hold: seconds the shared lock is held after the script starts.
            answer_at: second at which the onion starts to answer, None for never.

        Returns:
            Recreate time minus release time (None when it never recreated),
            the exit code, stderr, and whether the pending marker existed
            while the script waited.
        """
        reader = os.open(self.lock, os.O_RDONLY | os.O_CREAT, 0o644)
        fcntl.flock(reader, fcntl.LOCK_SH)
        proc = self.start(script, str(self.lock))
        began = time.monotonic()
        announced, released = False, None
        events = [(min(hold, 2.5), "look"), (hold, "release")]
        if answer_at is not None:
            events.append((answer_at, "answer"))
        for at, event in sorted(events):
            time.sleep(max(0.0, at - (time.monotonic() - began)))
            if event == "look":
                announced = self.pending.exists()
            elif event == "answer":
                self.answers.touch()
            else:
                released = time.time()
                fcntl.flock(reader, fcntl.LOCK_UN)
                os.close(reader)
        _, stderr = proc.communicate(timeout=20)
        recreated = None
        if self.marker.exists():
            recreated = float(self.marker.read_text()) - released  # nocheck: cache-read
        self.assertFalse(self.pending.exists())
        return recreated, proc.returncode, stderr, announced

    def test_the_recreate_waits_until_the_onion_run_releases_tor(self):
        recreated, rc, _, announced = self.run_script(self.SCRIPT, hold=3.0)
        self.assertIsNotNone(recreated)
        self.assertGreaterEqual(recreated, 0)
        self.assertTrue(announced)
        self.assertEqual(rc, 1)

    def test_onion_runs_outlasting_the_wait_skip_the_recreate_and_a_recovered_onion_passes(
        self,
    ):
        recreated, rc, stderr, _ = self.run_script(self.SCRIPT, hold=6.0, answer_at=3.0)
        self.assertIsNone(recreated)
        self.assertEqual(rc, 0)
        self.assertIn(
            "skipped recreating Tor for x.onion: onion Playwright runs held", stderr
        )

    def test_onion_runs_outlasting_the_wait_fail_only_this_probe_when_the_onion_stays_silent(
        self,
    ):
        recreated, rc, stderr, _ = self.run_script(self.SCRIPT, hold=6.0)
        self.assertIsNone(recreated)
        self.assertEqual(rc, 1)
        self.assertIn("skipped recreating Tor", stderr)

    def test_the_serial_run_recreates_at_once_without_touching_the_lock(self):
        began = time.time()
        proc = self.start(self.SCRIPT, "")
        stdout, _ = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 1)
        recreated = float(self.marker.read_text())  # nocheck: cache-read
        self.assertLess(recreated - began, 2 + 1.5)
        self.assertIn("recreating Tor for fresh circuits", stdout)
        self.assertNotIn("waiting up to", stdout)
        self.assertFalse(self.lock.exists())
        self.assertFalse(self.pending.exists())
