from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Self

from tests.integration.roles import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TASKS = PROJECT_ROOT / "roles/svc-ai-lmstudio/tasks"
BLOB = bytes(range(256)) * 1024
REPO = "lmstudio-community/Probe-GGUF"
FILE = "Probe-Q4_K_M.gguf"
OTHER = "Other-Q4_K_M.gguf"
GOOD = ("good", 0.0)
CORRUPT = ("corrupt", 0.0)
RATE = 1_000_000
RETRIES = 12
RETRY_DELAY = 5

PLAYBOOK = """
- hosts: localhost
  gather_facts: false
  tasks:
    - ansible.builtin.include_role:
        name: svc-ai-lmstudio
        tasks_from: utils/fetch.yml
"""


@dataclass(frozen=True)
class Model:
    """
    Args:
        file: the model's file name in the store.
        source: how its declared url answers, as a route of _serve.
        mirrors: how each of its mirrors answers, in order.
        held: what the store already holds at its path, None for nothing.
        declared: the bytes whose sha256 and size the model declares.
    """

    file: str
    source: tuple[str, float]
    mirrors: tuple[tuple[str, float], ...]
    held: bytes | None
    declared: bytes


@dataclass(frozen=True)
class Run:
    """
    Args:
        rc: the play's exit code.
        output: the play's output.
        stored: per model file, what the store holds afterwards (b"" when absent).
        requests: per URL path, how many requests it answered.
        peak: per model file, the most transfers of it in flight at once.
        overlap: the most transfers in flight at once, across every file.
        elapsed: the play's wall time in seconds.
        staged: what staging holds afterwards.
    """

    rc: int
    output: str
    stored: dict[str, bytes]
    requests: dict[str, int]
    peak: dict[str, int]
    overlap: int
    elapsed: float
    staged: list[str]

    def text(self) -> str:
        """
        Returns:
            The output with every run of whitespace folded to one space.
        """
        return " ".join(self.output.split())

    def items(self, marker: str) -> list[str]:
        """
        Args:
            marker: text a task header must contain.

        Returns:
            Every loop item line printed under a task whose header holds the marker.
        """
        lines: list[str] = []
        inside = False
        for line in self.output.splitlines():
            if line.startswith("TASK ["):
                inside = marker in line
            elif inside and "(item=" in line:
                lines.append(line)
        return lines


def _serve(
    routes: dict[str, tuple[str, float]], held: list[Path]
) -> tuple[ThreadingHTTPServer, dict]:
    """
    Args:
        routes: per URL path, how the source answers and a number of seconds.
            "good" sends BLOB, "corrupt" other bytes, "reset" cuts its first
            transfer off halfway with a TCP reset, "half" ends its first
            transfer cleanly after half the body, "trickle" sends a kilobyte
            every half second and gives up after a quarter of the body,
            "tamper" rewrites every held model with other bytes before it sends
            BLOB. Each of them waits the seconds before it answers, except
            "outage", which answers 503 until the seconds have passed since its
            first request and BLOB after that.
        held: the store paths "tamper" rewrites.

    Returns:
        The running source and its counters.
    """
    lock = threading.Lock()
    stats: dict = {
        "requests": {},
        "first": {},
        "flight": {},
        "peak": {},
        "active": 0,
        "overlap": 0,
    }

    class Source(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            kind, seconds = routes[self.path]
            file = self.path.rsplit("/", 1)[-1]
            with lock:
                attempt = stats["requests"].get(self.path, 0) + 1
                stats["requests"][self.path] = attempt
                first = stats["first"].setdefault(self.path, time.monotonic())
                stats["flight"][file] = stats["flight"].get(file, 0) + 1
                stats["peak"][file] = max(
                    stats["peak"].get(file, 0), stats["flight"][file]
                )
                stats["active"] += 1
                stats["overlap"] = max(stats["overlap"], stats["active"])
            try:
                if kind == "outage":
                    if time.monotonic() - first < seconds:
                        self.send_response(503)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                else:
                    time.sleep(seconds)
                self._answer(kind, attempt)
            except OSError:
                self.close_connection = True
            finally:
                with lock:
                    stats["flight"][file] -= 1
                    stats["active"] -= 1

        def _answer(self, kind: str, attempt: int) -> None:
            if kind == "tamper":
                for path in held:
                    forged = path.with_name(path.name + ".forged")
                    forged.write_bytes(bytes(reversed(BLOB)))
                    forged.replace(path)
            body = bytes(reversed(BLOB)) if kind == "corrupt" else BLOB
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if kind == "trickle":
                for offset in range(0, len(body) // 4, 1024):
                    self.wfile.write(body[offset : offset + 1024])
                    self.wfile.flush()
                    time.sleep(0.5)
                self.close_connection = True
                return
            if kind in ("reset", "half") and attempt == 1:
                self.wfile.write(body[: len(body) // 2])
                self.wfile.flush()
                if kind == "reset":
                    self.connection.setsockopt(
                        socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                    )
                    self.connection.close()
                self.close_connection = True
                return
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Source)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, stats


class Probe:
    """
    Args:
        models: the declared models and how their sources answer.
        floor: the download budget floor in seconds.
        rate: the slowest transfer rate a budget allows, in bytes per second.
        retries: how often an async download is retried within its budget.
        free: the free bytes df reports for the store, None for the real figure.
    """

    def __init__(
        self,
        models: list[Model],
        floor: int,
        rate: int,
        retries: int,
        free: int | None,
    ) -> None:
        self._scratch = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._scratch.name)
        self.models = models
        self.store = root / "store"
        self.staging = self.store / ".staging"
        self.jobs_file = Path(f"{self.staging}.jobs.json")
        self.async_dir = root / "ansible-async"
        held = [self.store / REPO / m.file for m in models if m.held is not None]
        routes: dict[str, tuple[str, float]] = {}
        for model in models:
            routes[f"/source/{model.file}"] = model.source
            for index, mirror in enumerate(model.mirrors, start=1):
                routes[f"/mirror{index}/{model.file}"] = mirror
        self.server, self.stats = _serve(routes, held)
        base = "http://{}:{}".format(*self.server.server_address[:2])
        (root / "tasks").symlink_to(PROJECT_ROOT / "tasks")
        declared = []
        for model in models:
            if model.held is not None:
                path = self.store / REPO / model.file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(model.held)
            entry = {
                "repo": REPO,
                "file": model.file,
                "url": f"{base}/source/{model.file}",
                "sha256": hashlib.sha256(model.declared).hexdigest(),
                "bytes": len(model.declared),
            }
            if model.mirrors:
                entry["mirrors"] = [
                    f"{base}/mirror{index}/{model.file}"
                    for index in range(1, len(model.mirrors) + 1)
                ]
            declared.append(entry)
        self.variables = root / "vars.json"
        self.settings = {
            "ansible_python_interpreter": sys.executable,
            "lmstudio_fetch_store": str(self.store),
            "lmstudio_fetch_staging": str(self.staging),
            "lmstudio_fetch_node": "localhost",
            "LMSTUDIO_PRELOAD_FLOOR_SECONDS": floor,
            "LMSTUDIO_PRELOAD_MIN_BYTES_PER_SECOND": rate,
            "LMSTUDIO_PRELOAD_RETRIES": retries,
            "LMSTUDIO_PRELOAD_RETRY_DELAY": RETRY_DELAY,
            "LMSTUDIO_PRELOAD_MODELS": declared,
        }
        playbook = root / "playbook.yml"
        playbook.write_text(PLAYBOOK, encoding="utf-8")
        self.command = [
            sys.executable,
            "-m",
            "ansible.cli.playbook",
            "-i",
            "localhost,",
            "-c",
            "local",
            str(playbook),
            "-e",
            f"@{self.variables}",
        ]
        self.env = {
            **os.environ,
            "ANSIBLE_CONFIG": str(PROJECT_ROOT / "ansible.cfg"),
            "ANSIBLE_ROLES_PATH": str(PROJECT_ROOT / "roles"),
            "ANSIBLE_HOME": str(root / "ansible-home"),
            "ANSIBLE_LOCAL_TEMP": str(root / "ansible-local"),
            "ANSIBLE_REMOTE_TEMP": str(root / "ansible-remote"),
            "ANSIBLE_ASYNC_DIR": str(self.async_dir),
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_DISPLAY_SKIPPED_HOSTS": "1",
        }
        if free is not None:
            bin_dir = root / "bin"
            bin_dir.mkdir()
            df = bin_dir / "df"
            df.write_text(
                "#!/bin/sh\n"
                "echo 'Filesystem 1-blocks Used Available Capacity Mounted on'\n"
                f"echo 'probe 0 0 {free} 0% /'\n",
                encoding="utf-8",
            )
            df.chmod(0o755)
            self.env["PATH"] = f"{bin_dir}{os.pathsep}{self.env['PATH']}"

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._scratch.cleanup()

    def leave_partial(self) -> None:
        """Leave the partial download an interrupted earlier fetch would."""
        self.staging.mkdir(parents=True, exist_ok=True)
        (self.staging / "tmpinterrupted").write_bytes(BLOB[:1024])

    def leave_dead_job(self) -> None:
        """Leave the jobs file of a fetch whose async job died before it ended."""
        self.async_dir.mkdir(parents=True, exist_ok=True)
        (self.async_dir / "1.dead").write_text(
            json.dumps({"started": 1, "finished": 0, "ansible_job_id": "1.dead"}),
            encoding="utf-8",
        )
        self.staging.mkdir(parents=True, exist_ok=True)
        self.jobs_file.write_text(
            json.dumps(
                {"lifetime": 5, "deadline": int(time.time()) - 1, "jobs": ["1.dead"]}
            ),
            encoding="utf-8",
        )

    def leave_unnoted_start(self, seconds: int) -> None:
        """Leave the jobs file of a fetch killed after it noted the start of its
        downloads but before it noted their job ids.

        Args:
            seconds: how long from now the downloads it started may run.
        """
        self.staging.mkdir(parents=True, exist_ok=True)
        self.jobs_file.write_text(
            json.dumps(
                {
                    "lifetime": seconds,
                    "deadline": int(time.time()) + seconds,
                    "jobs": [],
                }
            ),
            encoding="utf-8",
        )

    def deliver(self, file: str) -> None:
        """Land a model in the store the way a download the play did not start would.

        Args:
            file: the model file to land.
        """
        path = self.store / REPO / file
        path.parent.mkdir(parents=True, exist_ok=True)
        landing = path.with_name(path.name + ".landing")
        landing.write_bytes(BLOB)
        landing.replace(path)

    def noted_jobs(self) -> list[str]:
        """
        Returns:
            The job ids the jobs file notes, empty while it is absent or notes none.
        """
        try:
            noted = self.jobs_file.read_text(  # nocheck: cache-read  a running play rewrites it
                encoding="utf-8"
            )
        except FileNotFoundError:
            return []
        return json.loads(noted)["jobs"]

    def _configure(self, async_enabled: bool) -> None:
        """
        Args:
            async_enabled: whether the next play runs the downloads as async jobs.
        """
        self.variables.write_text(
            json.dumps(
                {
                    **self.settings,
                    "ASYNC_ENABLED": async_enabled,
                    "ASYNC_POLL": 0 if async_enabled else 10,
                }
            ),
            encoding="utf-8",
        )

    def start(self, async_enabled: bool) -> subprocess.Popen:
        """
        Args:
            async_enabled: whether the play runs the downloads as async jobs.

        Returns:
            The play, running in its own session.
        """
        self._configure(async_enabled)
        return subprocess.Popen(
            self.command,
            cwd=str(PROJECT_ROOT),
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def play(self, async_enabled: bool) -> Run:
        """
        Args:
            async_enabled: whether the play runs the downloads as async jobs.

        Returns:
            What one play did, with the source counters of every play so far.
        """
        self._configure(async_enabled)
        began = time.monotonic()
        result = subprocess.run(
            self.command,
            cwd=str(PROJECT_ROOT),
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
        )
        elapsed = time.monotonic() - began
        stored = {}
        for model in self.models:
            path = self.store / REPO / model.file
            stored[model.file] = (
                path.read_bytes()  # nocheck: cache-read  the play wrote it
                if path.exists()
                else b""
            )
        return Run(
            rc=result.returncode,
            output=result.stdout + result.stderr,
            stored=stored,
            requests=dict(self.stats["requests"]),
            peak=dict(self.stats["peak"]),
            overlap=self.stats["overlap"],
            elapsed=elapsed,
            staged=(
                sorted(entry.name for entry in self.staging.iterdir())
                if self.staging.exists()
                else []
            ),
        )


def _fetch(
    models: list[Model],
    floor: int,
    stale: bool,
    free: int | None,
    async_enabled: bool,
) -> Run:
    """
    Args:
        models: the declared models and how their sources answer.
        floor: the download budget floor in seconds.
        stale: whether an interrupted earlier fetch left a partial in staging.
        free: the free bytes df reports for the store, None for the real figure.
        async_enabled: whether the play runs the downloads as async jobs.

    Returns:
        What the play did.
    """
    with Probe(models, floor, RATE, RETRIES, free) as probe:
        if stale:
            probe.leave_partial()
        return probe.play(async_enabled)


def _include_of(tasks: list, target: str) -> dict | None:
    """
    Args:
        tasks: a parsed task list.
        target: the task file an include names.

    Returns:
        The first task, nested blocks included, that includes the target, else None.
    """
    for task in tasks or []:
        include = task.get("ansible.builtin.include_tasks")
        named = include.get("file") if isinstance(include, dict) else include
        if named == target:
            return task
        for key in ("block", "rescue"):
            nested = _include_of(task.get(key), target)
            if nested is not None:
                return nested
    return None


class TestFetch(unittest.TestCase):
    def test_every_model_downloads_at_once_when_async(self) -> None:
        run = _fetch(
            [
                Model(FILE, ("good", 3.0), (), None, BLOB),
                Model(OTHER, ("good", 3.0), (), None, BLOB),
            ],
            60,
            False,
            None,
            True,
        )
        self.assertEqual(run.rc, 0, run.output[-3000:])
        self.assertEqual(run.stored, {FILE: BLOB, OTHER: BLOB})
        self.assertEqual(run.overlap, 2)

    def test_debug_runs_download_one_model_at_a_time(self) -> None:
        run = _fetch(
            [
                Model(FILE, ("good", 3.0), (), None, BLOB),
                Model(OTHER, ("good", 3.0), (), None, BLOB),
            ],
            60,
            False,
            None,
            False,
        )
        self.assertEqual(run.rc, 0, run.output[-3000:])
        self.assertEqual(run.stored, {FILE: BLOB, OTHER: BLOB})
        self.assertEqual(run.overlap, 1)

    def test_debug_runs_give_each_model_its_own_budget(self) -> None:
        with Probe(
            [
                Model(FILE, ("trickle", 0.0), (), None, BLOB),
                Model(OTHER, GOOD, (), None, BLOB),
            ],
            1,
            len(BLOB) // 8,
            RETRIES,
            None,
        ) as probe:
            run = probe.play(False)
        self.assertNotEqual(run.rc, 0, run.output[-3000:])
        self.assertIn("Timed out after 8 second(s)", run.text(), run.output[-3000:])
        self.assertEqual(run.stored, {FILE: b"", OTHER: BLOB})

    def test_a_reset_transfer_costs_a_retry_not_the_deploy(self) -> None:
        for async_enabled in (True, False):
            with self.subTest(async_enabled=async_enabled):
                run = _fetch(
                    [Model(FILE, ("reset", 0.0), (), None, BLOB)],
                    60,
                    False,
                    None,
                    async_enabled,
                )
                self.assertEqual(run.rc, 0, run.output[-3000:])
                self.assertEqual(run.stored[FILE], BLOB)
                self.assertEqual(run.requests[f"/source/{FILE}"], 2)

    def test_a_twenty_second_source_outage_is_retried_through(self) -> None:
        for async_enabled in (True, False):
            with self.subTest(async_enabled=async_enabled):
                run = _fetch(
                    [Model(FILE, ("outage", 20.0), (), None, BLOB)],
                    60,
                    False,
                    None,
                    async_enabled,
                )
                self.assertEqual(run.rc, 0, run.output[-3000:])
                self.assertEqual(run.stored[FILE], BLOB)
                self.assertGreaterEqual(run.requests[f"/source/{FILE}"], 3)

    def test_async_retries_stop_when_the_source_budget_runs_out(self) -> None:
        run = _fetch([Model(FILE, CORRUPT, (), None, BLOB)], 20, False, None, True)
        self.assertNotEqual(run.rc, 0, run.output[-3000:])
        self.assertGreaterEqual(run.requests[f"/source/{FILE}"], 2)
        self.assertLessEqual(run.requests[f"/source/{FILE}"], 4)

    def test_an_interrupted_fetch_leaves_no_partial_behind(self) -> None:
        run = _fetch([Model(FILE, GOOD, (), None, BLOB)], 60, True, None, True)
        self.assertEqual(run.rc, 0, run.output[-3000:])
        self.assertEqual(run.stored[FILE], BLOB)
        self.assertEqual(run.staged, [])

    def test_a_cut_transfer_leaves_no_partial_for_the_next_attempt(self) -> None:
        run = _fetch(
            [Model(FILE, ("half", 0.0), (), None, BLOB)], 60, False, None, True
        )
        self.assertEqual(run.rc, 0, run.output[-3000:])
        self.assertEqual(run.stored[FILE], BLOB)
        self.assertEqual(run.requests[f"/source/{FILE}"], 2)
        self.assertEqual(run.staged, [])

    def test_a_source_that_never_verifies_fails_closed_inside_the_budget(self) -> None:
        run = _fetch([Model(FILE, CORRUPT, (), None, BLOB)], 4, False, None, True)
        self.assertNotEqual(run.rc, 0, run.output[-3000:])
        self.assertIn("did not match", run.text(), run.output[-3000:])
        self.assertEqual(run.stored[FILE], b"")
        self.assertEqual(run.requests[f"/source/{FILE}"], 1)
        self.assertLess(run.elapsed, 120)

    def test_a_corrupt_source_hands_over_to_the_next_mirror(self) -> None:
        with Probe(
            [Model(FILE, CORRUPT, (CORRUPT, GOOD), None, BLOB)], 60, RATE, 0, None
        ) as probe:
            run = probe.play(True)
        self.assertEqual(run.rc, 0, run.output[-3000:])
        self.assertEqual(run.stored[FILE], BLOB)
        self.assertEqual(run.requests[f"/mirror2/{FILE}"], 1)

    def test_a_corrupt_mirror_still_reaches_the_final_check(self) -> None:
        with Probe(
            [Model(FILE, CORRUPT, (CORRUPT,), None, BLOB)], 60, RATE, 0, None
        ) as probe:
            run = probe.play(True)
        self.assertNotEqual(run.rc, 0, run.output[-3000:])
        self.assertIn("What the sources answered:", run.text(), run.output[-3000:])
        answered = run.text().split("What the sources answered:", 1)[1]
        self.assertIn(f"/source/{FILE}: The checksum", answered)
        self.assertIn(f"/mirror1/{FILE}: The checksum", answered)
        self.assertEqual(run.stored[FILE], b"")

    def test_mirrors_wait_for_the_source_round_and_never_share_a_file(self) -> None:
        run = _fetch(
            [
                Model(FILE, ("good", 3.0), (GOOD,), None, BLOB),
                Model(OTHER, ("corrupt", 1.0), (("corrupt", 1.0), GOOD), None, BLOB),
            ],
            8,
            False,
            None,
            True,
        )
        self.assertEqual(run.rc, 0, run.output[-3000:])
        self.assertEqual(run.stored, {FILE: BLOB, OTHER: BLOB})
        self.assertNotIn(f"/mirror1/{FILE}", run.requests)
        self.assertEqual(run.requests[f"/mirror2/{OTHER}"], 1)
        self.assertEqual(run.peak, {FILE: 1, OTHER: 1})

    def test_a_trickling_download_is_cut_at_its_budget_and_collected(self) -> None:
        run = _fetch(
            [Model(FILE, ("trickle", 0.0), (), None, BLOB)], 5, False, None, True
        )
        self.assertNotEqual(run.rc, 0, run.output[-3000:])
        self.assertIn("Timeout exceeded", run.text(), run.output[-3000:])
        self.assertNotIn("still running past", run.text())
        self.assertEqual(run.stored[FILE], b"")
        self.assertEqual(run.staged, [])

    def test_a_killed_run_leaves_no_download_behind_for_the_next_one(self) -> None:
        for next_async in (True, False):
            with self.subTest(next_async=next_async):
                with Probe(
                    [Model(FILE, ("good", 8.0), (), None, BLOB)],
                    60,
                    RATE,
                    RETRIES,
                    None,
                ) as probe:
                    first = probe.start(True)
                    deadline = time.monotonic() + 120
                    while not probe.noted_jobs() and time.monotonic() < deadline:
                        time.sleep(0.2)
                    os.killpg(first.pid, signal.SIGKILL)
                    first.wait()
                    self.assertTrue(probe.noted_jobs())
                    run = probe.play(next_async)
                    self.assertFalse(probe.jobs_file.exists())
                self.assertEqual(run.rc, 0, run.output[-3000:])
                self.assertEqual(run.stored[FILE], BLOB)
                self.assertEqual(run.requests[f"/source/{FILE}"], 1)
                self.assertEqual(run.staged, [])

    def test_a_job_that_died_unfinished_is_dropped_at_its_deadline(self) -> None:
        with Probe(
            [Model(FILE, GOOD, (), None, BLOB)], 60, RATE, RETRIES, None
        ) as probe:
            probe.leave_dead_job()
            probe.leave_partial()
            run = probe.play(True)
            self.assertFalse(probe.jobs_file.exists())
        self.assertEqual(run.rc, 0, run.output[-3000:])
        self.assertEqual(run.stored[FILE], BLOB)
        self.assertEqual(run.staged, [])
        self.assertLess(run.elapsed, 120)

    def test_downloads_started_but_never_noted_are_waited_out(self) -> None:
        with Probe(
            [Model(FILE, GOOD, (), None, BLOB)], 60, RATE, RETRIES, None
        ) as probe:
            probe.leave_unnoted_start(30)
            probe.leave_partial()
            landing = threading.Timer(20, probe.deliver, args=(FILE,))
            landing.start()
            try:
                run = probe.play(True)
            finally:
                landing.cancel()
            self.assertFalse(probe.jobs_file.exists())
        self.assertEqual(run.rc, 0, run.output[-3000:])
        self.assertEqual(run.stored[FILE], BLOB)
        self.assertEqual(run.requests, {})
        self.assertEqual(run.staged, [])

    def test_debug_runs_retry_a_download_only_preload_retries_times(self) -> None:
        with Probe(
            [Model(FILE, ("outage", 600.0), (), None, BLOB)], 60, RATE, 1, None
        ) as probe:
            run = probe.play(False)
        self.assertNotEqual(run.rc, 0, run.output[-3000:])
        self.assertEqual(run.requests[f"/source/{FILE}"], 2, run.output[-3000:])

    def test_debug_runs_cap_every_retry_of_a_source_at_its_budget(self) -> None:
        run = _fetch(
            [Model(FILE, ("corrupt", 2.0), (), None, BLOB)], 6, False, None, False
        )
        self.assertNotEqual(run.rc, 0, run.output[-3000:])
        self.assertIn("Timed out after 6 second(s)", run.text(), run.output[-3000:])
        self.assertLessEqual(run.requests[f"/source/{FILE}"], 2)

    def test_a_negative_retry_count_is_refused(self) -> None:
        with Probe([Model(FILE, GOOD, (), None, BLOB)], 60, RATE, -1, None) as probe:
            run = probe.play(True)
        self.assertNotEqual(run.rc, 0, run.output[-3000:])
        self.assertIn("must not be negative", run.text(), run.output[-3000:])
        self.assertEqual(run.requests, {})

    def test_a_model_rewritten_during_the_fetch_is_judged_again(self) -> None:
        run = _fetch(
            [
                Model(FILE, GOOD, (), BLOB, BLOB),
                Model(OTHER, ("tamper", 0.0), (), None, BLOB),
            ],
            60,
            False,
            None,
            True,
        )
        self.assertNotEqual(run.rc, 0, run.output[-3000:])
        self.assertIn(f"{FILE} in the model store", run.text(), run.output[-3000:])
        self.assertEqual(run.stored[OTHER], BLOB)

    def test_the_free_space_check_sums_every_pending_model(self) -> None:
        run = _fetch(
            [Model(FILE, GOOD, (), None, BLOB), Model(OTHER, GOOD, (), None, BLOB)],
            60,
            False,
            len(BLOB) * 3 // 2,
            True,
        )
        self.assertNotEqual(run.rc, 0, run.output[-3000:])
        self.assertIn("GiB free but needs", run.text(), run.output[-3000:])
        self.assertEqual(run.requests, {})

    def test_an_absent_model_counts_once_against_the_free_space(self) -> None:
        run = _fetch(
            [Model(FILE, GOOD, (), None, BLOB)], 60, False, len(BLOB) * 3 // 2, True
        )
        self.assertEqual(run.rc, 0, run.output[-3000:])
        self.assertEqual(run.stored[FILE], BLOB)

    def test_a_model_declared_twice_is_fetched_once(self) -> None:
        run = _fetch(
            [Model(FILE, GOOD, (), None, BLOB), Model(FILE, GOOD, (), None, BLOB)],
            60,
            False,
            len(BLOB) * 3 // 2,
            True,
        )
        self.assertEqual(run.rc, 0, run.output[-3000:])
        self.assertEqual(run.stored[FILE], BLOB)
        self.assertEqual(run.requests[f"/source/{FILE}"], 1)
        self.assertEqual(run.peak, {FILE: 1})

    def test_a_path_declared_with_two_digests_is_refused(self) -> None:
        run = _fetch(
            [
                Model(FILE, GOOD, (), None, BLOB),
                Model(FILE, GOOD, (), None, bytes(reversed(BLOB))),
            ],
            60,
            False,
            None,
            True,
        )
        self.assertNotEqual(run.rc, 0, run.output[-3000:])
        self.assertIn("declares the same repo and file", run.text(), run.output[-3000:])
        self.assertEqual(run.requests, {})

    def test_a_held_model_with_another_digest_counts_as_pending(self) -> None:
        held = bytes(reversed(BLOB))
        run = _fetch(
            [Model(FILE, GOOD, (), held, BLOB)], 60, False, len(BLOB) // 2, True
        )
        self.assertNotEqual(run.rc, 0, run.output[-3000:])
        self.assertIn("GiB free but needs", run.text(), run.output[-3000:])
        self.assertEqual(run.stored[FILE], held)
        self.assertEqual(run.requests, {})

    def test_a_held_model_is_read_once_and_never_fetched(self) -> None:
        run = _fetch(
            [Model(FILE, CORRUPT, (), BLOB, BLOB), Model(OTHER, GOOD, (), None, BLOB)],
            60,
            False,
            None,
            True,
        )
        self.assertEqual(run.rc, 0, run.output[-3000:])
        self.assertEqual(run.stored, {FILE: BLOB, OTHER: BLOB})
        self.assertEqual(
            len([line for line in run.items("🔍 Read") if f"(item={FILE})" in line]),
            1,
            run.output[-3000:],
        )
        self.assertEqual(
            [line for line in run.items("⬇️") if f"(item={FILE}" in line], []
        )
        self.assertTrue(
            [line for line in run.items("⬇️") if f"(item={OTHER} from " in line]
        )
        self.assertNotIn(f"/source/{FILE}", run.requests)

    def test_the_swarm_seed_and_the_node_preload_share_one_fetch(self) -> None:
        for caller in ("00_core.yml", "utils/preload/node.yml"):
            with self.subTest(caller=caller):
                self.assertIsNotNone(
                    _include_of(
                        load_yaml_any(str(TASKS / caller), default_if_missing=[]),
                        "utils/fetch.yml",
                    )
                )

    def test_every_fetch_job_is_collected_on_the_node_that_runs_it(self) -> None:
        for caller in ("00_core.yml", "utils/preload/node.yml"):
            with self.subTest(caller=caller):
                include = _include_of(
                    load_yaml_any(str(TASKS / caller), default_if_missing=[]),
                    "utils/fetch.yml",
                )
                self.assertEqual(
                    include["ansible.builtin.include_tasks"]["apply"]["delegate_to"],
                    include["vars"]["lmstudio_fetch_node"],
                )
        reap = _include_of(
            load_yaml_any(
                str(TASKS / "utils/fetch/collect.yml"), default_if_missing=[]
            ),
            "utils/async/reap.yml",
        )
        self.assertEqual(
            reap["ansible.builtin.include_tasks"]["apply"]["delegate_to"],
            "{{ lmstudio_fetch_node }}",
        )


if __name__ == "__main__":
    unittest.main()
