#!/usr/bin/env python3
"""Run the round's Playwright containers with a concurrency cap.

    run_parallel.py <jobs_dir> <cap> <poll_seconds> <max_cpu_pressure>
                    <ram_fraction> <sustain_seconds> <tor_lock> <onion_cap>

Ansible drops one ``<seq>-<application_id>.job.json`` per role into
*jobs_dir* while it stages the next role, and touches ``sealed`` once the last
one is written. Each job file holds ``id``, ``argv``, ``env``, ``timeout``,
``after``, ``tor``, ``workers``, ``memory_mb``, ``stop`` and ``meta``. The
scheduler starts a job once every job it names in ``after`` has finished here,
never runs more than *cap* at once, starts ready jobs in submission order, and
writes ``<application_id>.result.json`` with ``meta``, ``rc`` (absent and
``msg`` set when the timeout killed it), ``timed_out``, the ``run_signals``
fields, ``stdout`` and ``stderr``. A job whose ``after`` names one that never
ran here gets only ``id``, ``meta`` and ``deferred``, the jobs it waited on.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

SEALED = "sealed"
JOB_NAME = re.compile(r"^(\d+)-.+\.job\.json$")
RESULT_SUFFIX = ".result.json"
KILL_GRACE_SECONDS = 10
NAP_STEP_SECONDS = 0.1
RETRY_MARK = re.compile(r"\(retry #\d+\)")
FLAKY_SUMMARY = re.compile(r"^\s*(\d+) flaky\s*$", re.MULTILINE)
CRASH_MARKS = {
    "page crashed": re.compile(r"(?i)(?:page|target) crashed"),
    "browser closed (OOM or timeout)": re.compile(r"(?i)browser (?:has been )?closed"),
    "worker killed": re.compile(
        r"(?i)worker process exited unexpectedly.*|\bSIGKILL\b"
    ),
}


@dataclass(frozen=True)
class Job:
    id: str
    after: tuple[str, ...]


class Plan:
    """Dispatch order of a streamed job list under a concurrency cap.

    Args:
        cap: most jobs that may run at once, at least one.
    """

    def __init__(self, cap: int) -> None:
        if cap < 1:
            raise ValueError(f"cap must be at least 1, got {cap}")
        self.cap = cap
        self.pending: list[Job] = []
        self.submitted: set[str] = set()
        self.running: set[str] = set()
        self.finished: set[str] = set()
        self.deferred: set[str] = set()
        self.sealed = False

    def submit(self, job: Job) -> None:
        if job.id in self.submitted:
            raise ValueError(f"job {job.id} submitted twice")
        self.submitted.add(job.id)
        self.pending.append(job)

    def seal(self) -> None:
        self.sealed = True

    def _ready(self, job: Job) -> bool:
        return all(dep in self.finished for dep in job.after if dep != job.id)

    def start_next(
        self,
        host_admits: Callable[[int, Job], bool] = lambda running, job: True,
        job_admits: Callable[[Job], bool] = lambda job: True,
        job_release: Callable[[Job], None] = lambda job: None,
    ) -> list[Job]:
        """Jobs to start now, in submission order, within the cap.

        Args:
            host_admits: asked with the running count and the ready job before
                each start; a False ends this round of starts.
            job_admits: asked first for each ready job, claiming what the job
                needs; a False skips that job only, so a job waiting on its
                own resource never uses up the host's admission.
            job_release: hands back what *job_admits* claimed when the host
                then refuses the job.

        Returns:
            The started jobs, already counted as running.
        """
        started: list[Job] = []
        for job in list(self.pending):
            if len(self.running) >= self.cap:
                break
            if not self._ready(job):
                continue
            if not job_admits(job):
                continue
            if not host_admits(len(self.running), job):
                job_release(job)
                break
            self.pending.remove(job)
            self.running.add(job.id)
            started.append(job)
        return started

    def defer_orphans(self) -> list[Job]:
        """Pull the jobs of a sealed list whose ``after`` can never finish here.

        Returns:
            Jobs that wait on one never submitted, such as an app staging
            dropped, or on one deferred, so they run serially after it instead.

        Raises:
            RuntimeError: nothing runs and the remaining jobs wait on each other.
        """
        deferred: list[Job] = []
        while self.sealed and (orphans := [j for j in self.pending if self._orphan(j)]):
            for job in orphans:
                self.pending.remove(job)
                self.deferred.add(job.id)
            deferred += orphans
        stuck = self.sealed and self.pending and not self.running
        if stuck and not any(self._ready(job) for job in self.pending):
            raise RuntimeError(f"unsatisfiable after: {self.pending}")
        return deferred

    def _orphan(self, job: Job) -> bool:
        return bool(set(job.after) - {job.id} - (self.submitted - self.deferred))

    def finish(self, job_id: str) -> None:
        self.running.remove(job_id)
        self.finished.add(job_id)

    def done(self) -> bool:
        return self.sealed and not self.pending and not self.running


class HostGate:
    """Admit one more container only while the host has room for it.

    The first container always starts, so the round never runs slower than
    the serial runner.

    The scheduler samples the host on every pass, whether or not a job waits.
    A further container needs CPU pressure at or below the ceiling in both
    the 10 s and the 60 s average on every sample of a sustained window that
    began after the last start; one sample above the ceiling restarts the
    window. Running containers are never stopped, so their results stay real.

    Args:
        max_cpu_pressure: highest CPU ``some`` pressure, in percent, in both
            ``avg10`` and ``avg60``. WordPress#0's serial run peaked at 35.9 %
            ``some avg60`` (run 41926377524), so no browser is added while the
            host stalls more than it already did serially.
        ram_fraction: share of MemAvailable one container's memory estimate
            may claim, the fraction ``playwright_workers`` sizes browsers by.
        sustain_seconds: how long every sample must stay calm before another
            container starts.
        pressure_path: the kernel's CPU pressure file.
        meminfo_path: the kernel's meminfo file.
        clock: monotonic clock.
    """

    def __init__(
        self,
        max_cpu_pressure: float,
        ram_fraction: float,
        sustain_seconds: float,
        pressure_path: Path,
        meminfo_path: Path,
        clock: Callable[[], float],
    ) -> None:
        self.max_cpu_pressure = max_cpu_pressure
        self.ram_fraction = ram_fraction
        self.sustain_seconds = sustain_seconds
        self.pressure_path = pressure_path
        self.meminfo_path = meminfo_path
        self.clock = clock
        self.calm_since: float | None = None
        self.available_mb: float | None = None

    def cpu_pressure(self) -> tuple[float, float] | None:
        try:
            for line in self.pressure_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("some "):
                    fields = dict(f.split("=") for f in line.split()[1:])
                    return float(fields["avg10"]), float(fields["avg60"])
        except (OSError, KeyError, ValueError):
            return None
        return None

    def mem_available_mb(self) -> float | None:
        try:
            for line in self.meminfo_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024
        except (OSError, ValueError, IndexError):
            return None
        return None

    def observe(self) -> None:
        """Take one sample and extend or restart the calm window."""
        pressure = self.cpu_pressure()
        self.available_mb = self.mem_available_mb()
        calm = (
            pressure is not None
            and self.available_mb is not None
            and max(pressure) <= self.max_cpu_pressure
        )
        if not calm:
            self.calm_since = None
        elif self.calm_since is None:
            self.calm_since = self.clock()

    def admits(self, running: int, memory_mb: float) -> bool:
        """Whether one more container may start now; a yes restarts the window.

        Args:
            running: containers already running.
            memory_mb: the memory estimate of the container that would start.

        Returns:
            True for the first container, otherwise only after a full calm
            window and when the estimate fits the RAM fraction of what the
            last sample found available.
        """
        room = running == 0 or (
            self.calm_since is not None
            and self.clock() - self.calm_since >= self.sustain_seconds
            and self.available_mb is not None
            and memory_mb <= self.available_mb * self.ram_fraction
        )
        if room:
            self.calm_since = None
        return room


class TorReaders:
    """Shared locks the running onion jobs hold on the Tor lock file.

    ``wait_onion_reachable.sh`` takes the exclusive lock before it recreates
    Tor, so a recreate waits until no onion job runs, and no onion job starts
    while a recreate holds it. Linux ``flock`` does not prefer a waiting
    writer, so the script announces itself with ``<path>.recreate-pending``
    and no new shared lock is taken while that file exists. A probe killed
    before its exit trap ran leaves that file behind, so ``main`` removes it
    at startup, before staging can probe Tor for this round. The browsers of
    all running onion jobs together stay within *onion_cap*, the Tor ceiling
    ``playwright_workers`` sizes one suite by, since every browser holds its
    own circuits on the one shared daemon.

    Args:
        path: the lock file both sides open.
        onion_cap: most browser workers that may run over Tor at once.
    """

    def __init__(self, path: Path, onion_cap: int) -> None:
        self.path = path
        self.pending = path.with_name(path.name + ".recreate-pending")
        self.onion_cap = onion_cap
        self.fds: dict[str, int] = {}
        self.workers: dict[str, int] = {}

    def acquire(self, job_id: str, workers: int) -> bool:
        if self.workers and sum(self.workers.values()) + workers > self.onion_cap:
            return False
        if self.pending.exists():
            return False
        fd = os.open(self.path, os.O_RDONLY | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        self.fds[job_id] = fd
        self.workers[job_id] = workers
        return True

    def release(self, job_id: str) -> None:
        self.workers.pop(job_id, None)
        fd = self.fds.pop(job_id, None)
        if fd is not None:
            os.close(fd)


def _load_jobs(jobs_dir: Path, seen: set[str]) -> list[dict]:
    named = []
    for path in jobs_dir.iterdir():
        match = JOB_NAME.match(path.name)
        if match and path.name not in seen:
            named.append((int(match.group(1)), path))
    seen.update(path.name for _, path in named)
    return [json.loads(path.read_text(encoding="utf-8")) for _, path in sorted(named)]


def _write_result(jobs_dir: Path, job_id: str, result: dict) -> None:
    tmp = jobs_dir / f".{job_id}.result.tmp"
    tmp.write_text(json.dumps(result), encoding="utf-8")
    tmp.replace(jobs_dir / f"{job_id}{RESULT_SUFFIX}")


def _stop(proc: subprocess.Popen, stop_argv: list[str]) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            proc.wait(timeout=KILL_GRACE_SECONDS)
            break
        except subprocess.TimeoutExpired:
            continue
    subprocess.run(
        stop_argv, stdin=subprocess.DEVNULL, capture_output=True, check=False
    )


def _nap(procs: list[subprocess.Popen], seconds: float) -> None:
    """Sleep up to *seconds*, waking as soon as one of *procs* exits."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if any(proc.poll() is not None for proc in procs):
            return
        time.sleep(min(NAP_STEP_SECONDS, max(0.0, deadline - time.monotonic())))


def run_signals(output: str) -> dict[str, int]:
    """What a run's output tells beyond its exit code.

    Args:
        output: the container's stdout and stderr.

    Returns:
        ``retries``: attempts Playwright repeated, from its ``(retry #N)``
        marks; ``flaky``: tests that passed only on a retry, from its summary;
        ``crashes``: crashed pages, closed browsers and killed test workers,
        the shapes an OOM kill takes, even when a retry later passed;
        ``crash_kinds``: those counts by kind, for example
        ``page crashed 1, worker killed 2``, empty when there were none.
    """
    flaky = FLAKY_SUMMARY.findall(output)
    kinds = {kind: len(mark.findall(output)) for kind, mark in CRASH_MARKS.items()}
    return {
        "retries": len(RETRY_MARK.findall(output)),
        "flaky": int(flaky[-1]) if flaky else 0,
        "crashes": sum(kinds.values()),
        "crash_kinds": ", ".join(
            f"{kind} {count}" for kind, count in kinds.items() if count
        ),
    }


def _raise_on_signal(signum, _frame):
    raise SystemExit(128 + signum)


def run(jobs_dir: Path, cap: int, poll: float, gate: HostGate, tor: TorReaders) -> int:
    """Drive the jobs in *jobs_dir* until the list is sealed and drained.

    Args:
        jobs_dir: directory Ansible streams job files into.
        cap: most containers running at once.
        poll: seconds between scans of *jobs_dir* and the running jobs.
        gate: decides whether the host has room for one more container.
        tor: shared Tor locks for onion jobs.

    Returns:
        0 once every job has a result file; a job's own failure lives in its
        result, so it never aborts the others. On any exit, crash or signal
        included, every container still running is stopped.
    """
    plan = Plan(cap)
    seen: set[str] = set()
    specs: dict[str, dict] = {}
    running: dict[str, tuple[subprocess.Popen, float, float, Path, Path]] = {}

    def job_admits(job: Job) -> bool:
        spec = specs[job.id]
        return not spec["tor"] or tor.acquire(job.id, int(spec["workers"]))

    try:
        while True:
            for job_id, (proc, started, deadline, out_path, err_path) in list(
                running.items()
            ):
                rc = proc.poll()
                timed_out = rc is None and time.monotonic() > deadline
                if rc is None and not timed_out:
                    continue
                result = {
                    "meta": specs[job_id]["meta"],
                    "timed_out": timed_out,
                    "seconds": round(time.monotonic() - started, 1),
                    "ended_at": round(time.time(), 1),
                }
                if timed_out:
                    _stop(proc, specs[job_id]["stop"])
                    result["msg"] = (
                        f"killed after its {specs[job_id]['timeout']}s timeout"
                    )
                else:
                    result["rc"] = rc
                result["stdout"] = out_path.read_text(
                    encoding="utf-8", errors="replace"
                )
                result["stderr"] = err_path.read_text(
                    encoding="utf-8", errors="replace"
                ) + (f"\n[run_parallel] {result['msg']}\n" if timed_out else "")
                result.update(run_signals(result["stdout"] + result["stderr"]))
                _write_result(jobs_dir, job_id, result)
                del running[job_id]
                tor.release(job_id)
                plan.finish(job_id)
            sealed_now = (jobs_dir / SEALED).exists()
            for spec in _load_jobs(jobs_dir, seen):
                specs[spec["id"]] = spec
                plan.submit(Job(spec["id"], tuple(spec["after"])))
            if sealed_now:
                plan.seal()
            gate.observe()
            for job in plan.start_next(
                lambda count, ready: gate.admits(
                    count, float(specs[ready.id]["memory_mb"])
                ),
                job_admits,
                lambda refused: tor.release(refused.id),
            ):
                spec = specs[job.id]
                out_path = jobs_dir / f"{job.id}.stdout"
                err_path = jobs_dir / f"{job.id}.stderr"
                with out_path.open("wb") as out, err_path.open("wb") as err:
                    proc = subprocess.Popen(
                        spec["argv"],
                        env={**os.environ, **spec["env"]},
                        stdin=subprocess.DEVNULL,
                        stdout=out,
                        stderr=err,
                        start_new_session=True,
                    )
                started = time.monotonic()
                running[job.id] = (
                    proc,
                    started,
                    started + float(spec["timeout"]),
                    out_path,
                    err_path,
                )
            for job in plan.defer_orphans():
                waits = [dep for dep in job.after if dep not in plan.finished]
                meta = specs[job.id]["meta"]
                result = {"id": job.id, "meta": meta, "deferred": waits}
                _write_result(jobs_dir, job.id, result)
            if plan.done():
                return 0
            _nap([entry[0] for entry in running.values()], poll)
    finally:
        for job_id, (proc, *_rest) in running.items():
            _stop(proc, specs[job_id]["stop"])
            tor.release(job_id)


def main(argv: list[str]) -> int:
    signal.signal(signal.SIGTERM, _raise_on_signal)
    signal.signal(signal.SIGHUP, _raise_on_signal)
    jobs_dir, cap, poll, max_cpu, ram_fraction, sustain, tor_lock, onion_cap = argv
    gate = HostGate(
        float(max_cpu),
        float(ram_fraction),
        float(sustain),
        Path("/proc/pressure/cpu"),
        Path("/proc/meminfo"),
        time.monotonic,
    )
    tor = TorReaders(Path(tor_lock), int(onion_cap))
    tor.pending.unlink(missing_ok=True)
    return run(Path(jobs_dir), int(cap), float(poll), gate, tor)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
