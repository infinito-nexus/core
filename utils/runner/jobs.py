from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import json
import re
import secrets
from typing import TYPE_CHECKING

from utils.env.handlers.infinito.cache.paths import machine

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from pathlib import Path
    from typing import TextIO

QUEUED = "queued"
RUNNING = "running"
HELD = "held"
DONE = "done"
FAILED = "failed"
ENDED = (DONE, FAILED)
IDLE = "idle"
BUSY = "busy"
RELEASE = "make runner-release job={id}"

_DURATION = re.compile(r"^\s*(\d+)\s*([smhd])\s*$")
_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class JobError(RuntimeError):
    pass


class QueueTimeoutError(JobError):
    pass


@dataclasses.dataclass(frozen=True)
class Job:
    id: str
    checkout: str
    target: str
    args: tuple[str, ...]
    hold: bool
    state: str
    submitted_at: float
    runner: str | None = None
    stack: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    exit_code: int | None = None


def parse_duration(value: str) -> int:
    """Args:
        value: whole seconds, minutes, hours or days, as in ``90s``, ``30m``, ``24h`` or ``7d``.

    Raises:
        JobError: the value names no duration.
    """
    match = _DURATION.match(value)
    if match is None:
        raise JobError(f"'{value}' is no duration like 30m, 24h or 7d")
    return int(match[1]) * _SECONDS[match[2]]


def queue_root() -> Path:
    """Return the machine-wide queue every checkout submits to.

    It sits beside the machine-wide cache base, not below it, so neither
    ``make cache-evict`` nor ``make clean-cache`` ever touches a job record,
    and like the infra lock it stays put when a shell exports another base.
    """
    return machine().parent / "jobs"


def _jobs(root: Path) -> Path:
    return root / "jobs"


def log_path(root: Path, job_id: str) -> Path:
    """
    Args:
        root: the queue directory.
        job_id: the job.
    """
    return root / "logs" / f"{job_id}.log"


@contextlib.contextmanager
def _locked(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _write(root: Path, job: Job) -> Job:
    folder = _jobs(root)
    folder.mkdir(parents=True, exist_ok=True)
    staged = folder / f".{job.id}.json"
    with staged.open("w", encoding="utf-8") as handle:
        json.dump(dataclasses.asdict(job), handle, sort_keys=True)
    staged.replace(folder / f"{job.id}.json")
    return job


def _read(path: Path) -> Job:
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return Job(**{**raw, "args": tuple(raw["args"])})


def jobs(root: Path) -> list[Job]:
    """Args:
        root: the queue directory.

    Returns:
        Every job record, oldest submission first.
    """
    folder = _jobs(root)
    if not folder.is_dir():
        return []
    found = [
        _read(path) for path in folder.glob("*.json") if not path.name.startswith(".")
    ]
    return sorted(found, key=lambda job: (job.submitted_at, job.id))


def job(root: Path, job_id: str) -> Job:
    """Args:
        root: the queue directory.
        job_id: the job.

    Raises:
        JobError: no such job.
    """
    path = _jobs(root) / f"{job_id}.json"
    if not path.is_file():
        raise JobError(f"no job {job_id} in {root}")
    return _read(path)


def submit(
    root: Path, checkout: str, target: str, args: Iterable[str], hold: bool, now: float
) -> Job:
    """
    Args:
        root: the queue directory.
        checkout: the absolute path of the invoking checkout.
        target: the deploy target the job runs.
        args: its arguments.
        hold: keep the job's stack after the deploy until a release.
        now: the submission time.
    """
    record = Job(
        id=f"{int(now * 1000):012x}-{secrets.token_hex(3)}",
        checkout=checkout,
        target=target,
        args=tuple(args),
        hold=hold,
        state=QUEUED,
        submitted_at=now,
    )
    with _locked(root):
        log = log_path(root, record.id)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.touch()
        return _write(root, record)


def register(root: Path, runner: str) -> None:
    """
    Args:
        root: the queue directory.
        runner: the name of a pool runner that takes jobs from this queue.
    """
    folder = root / "runners"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / runner).touch()


def runners(root: Path) -> dict[str, str]:
    """Args:
        root: the queue directory.

    Returns:
        Every registered runner with its state: idle, busy or held.
    """
    folder = root / "runners"
    names = sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []
    states = dict.fromkeys(names, IDLE)
    for record in jobs(root):
        if record.runner in states and record.state in (RUNNING, HELD):
            states[record.runner] = BUSY if record.state == RUNNING else HELD
    return states


def claim(root: Path, runner: str, stack: str, now: float) -> Job | None:
    """Args:
        root: the queue directory.
        runner: the idle runner asking for work.
        stack: the compose project name of the runner's job stack.
        now: the claim time.

    Returns:
        The oldest queued job, now running on ``runner``; None when the runner is not idle or nothing waits.
    """
    with _locked(root):
        if runners(root).get(runner, IDLE) != IDLE:
            return None
        queued = [record for record in jobs(root) if record.state == QUEUED]
        if not queued:
            return None
        return _write(
            root,
            dataclasses.replace(
                queued[0], state=RUNNING, runner=runner, stack=stack, started_at=now
            ),
        )


def finish(root: Path, job_id: str, exit_code: int, now: float) -> Job:
    """Args:
        root: the queue directory.
        job_id: the running job.
        exit_code: the deploy's exit status.
        now: the end time.

    Returns:
        The job, held when it was submitted with hold, else done or failed by its exit status.
    """
    with _locked(root):
        record = job(root, job_id)
        if record.state != RUNNING:
            raise JobError(f"job {job_id} is {record.state}, not {RUNNING}")
        state = HELD if record.hold else DONE if exit_code == 0 else FAILED
        return _write(
            root,
            dataclasses.replace(record, state=state, exit_code=exit_code, ended_at=now),
        )


def release(root: Path, job_id: str) -> Job:
    """Args:
        root: the queue directory.
        job_id: the held job whose stack the caller has torn down.

    Returns:
        The job, done or failed by its exit status; its runner is idle again.
    """
    with _locked(root):
        record = job(root, job_id)
        if record.state != HELD:
            raise JobError(f"job {job_id} is {record.state}, not {HELD}")
        state = DONE if record.exit_code == 0 else FAILED
        return _write(root, dataclasses.replace(record, state=state))


def withdraw(root: Path, job_id: str) -> None:
    """Args:
        root: the queue directory.
        job_id: the queued job to drop.

    Raises:
        JobError: the job is no longer queued.
    """
    with _locked(root):
        record = job(root, job_id)
        if record.state != QUEUED:
            raise JobError(f"job {job_id} is {record.state}, not {QUEUED}")
        (_jobs(root) / f"{job_id}.json").unlink()
        log_path(root, job_id).unlink(missing_ok=True)


def position(root: Path, job_id: str) -> int:
    """Args:
        root: the queue directory.
        job_id: a queued job.

    Returns:
        Its 1-based place among the queued jobs, 0 when it is not queued.
    """
    queued = [record.id for record in jobs(root) if record.state == QUEUED]
    return queued.index(job_id) + 1 if job_id in queued else 0


def _waiting_note(root: Path, job_id: str, place: int) -> str:
    held = [record for record in jobs(root) if record.state == HELD]
    lines = [f"[runner] job {job_id} waits at queue position {place}"]
    lines.extend(
        f"[runner]   held: job {record.id} on {record.runner}, release with "
        + RELEASE.format(id=record.id)
        for record in held
    )
    return "\n".join(lines)


def wait_until_started(
    root: Path,
    job_id: str,
    timeout: int | None,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    out: TextIO,
    poll: float,
) -> Job:
    """Args:
        root: the queue directory.
        job_id: the submitted job.
        timeout: seconds to wait for a runner, None to wait without limit.
        clock: returns the current time.
        sleep: waits the given seconds.
        out: where the queue position, the held jobs and the release command go.
        poll: seconds between two looks at the queue.

    Returns:
        The job once a runner has claimed it.

    Raises:
        QueueTimeoutError: the timeout passed first; the job is withdrawn.
    """
    started = clock()
    shown = None
    while True:
        record = job(root, job_id)
        if record.state != QUEUED:
            return record
        place = position(root, job_id)
        if place != shown:
            print(_waiting_note(root, job_id, place), file=out, flush=True)
            shown = place
        if timeout is not None and clock() - started >= timeout:
            withdraw(root, job_id)
            raise QueueTimeoutError(
                f"job {job_id} withdrawn: timeout={timeout}s passed at queue position {place}"
            )
        sleep(poll)


def follow(
    root: Path, job_id: str, out: TextIO, sleep: Callable[[float], None], poll: float
) -> int:
    """Args:
        root: the queue directory.
        job_id: a claimed job.
        out: where the job's log goes.
        sleep: waits the given seconds.
        poll: seconds between two looks at the log.

    Returns:
        The job's exit status once its deploy has ended.
    """
    offset = 0
    while True:
        record = job(root, job_id)
        with log_path(root, job_id).open(encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            chunk = handle.read()
            offset = handle.tell()
        if chunk:
            out.write(chunk)
            out.flush()
        if record.state in (HELD, *ENDED) and record.exit_code is not None:
            return record.exit_code
        sleep(poll)


def cleanup_report(
    root: Path, stacks: Iterable[str], now: float
) -> tuple[list[tuple[Job, float]], list[str]]:
    """Args:
        root: the queue directory.
        stacks: the compose project names of every job stack that exists.
        now: the current time.

    Returns:
        Every held job with its age in seconds, and every stack no running or held job owns.
    """
    records = jobs(root)
    held = [
        (record, now - record.ended_at)
        for record in records
        if record.state == HELD and record.ended_at is not None
    ]
    owned = {record.stack for record in records if record.state in (RUNNING, HELD)}
    return held, sorted(set(stacks) - owned)
