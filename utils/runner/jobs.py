from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import os
import re
import secrets
from typing import TYPE_CHECKING

from utils.env.handlers.infinito.cache.paths import machine
from utils.runner.store import (
    _ASSIGNMENT,
    _TARGET,
    DONE,
    ENDED,
    FAILED,
    HELD,
    QUEUED,
    RUNNING,
    Job,
    JobError,
    _jobs,
    _locked,
    _regular_fd,
    _shared_fd,
    _write,
    checked_name,
    ensure_queue,
    failure,
    is_serving,
    job,
    jobs,
    log_path,
    open_log,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from pathlib import Path
    from typing import TextIO

IDLE = "idle"
BUSY = "busy"
RELEASE = "make runner-release job={id}"

_DURATION = re.compile(r"^\s*(\d+)\s*([smhd])\s*$")
_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class QueueTimeoutError(JobError):
    pass


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
    """Returns:
    The machine-wide queue every checkout submits to: ``jobs`` below the
    cache base the paths SPOT names.
    """
    return machine() / "jobs"


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

    Raises:
        JobError: the target is no make target name or an argument is no
            ``NAME=value`` assignment, which the runner would refuse to read.
    """
    args = tuple(args)
    if _TARGET.fullmatch(target) is None:
        raise JobError(f"{target!r} is no make target")
    unassigned = [arg for arg in args if _ASSIGNMENT.fullmatch(arg) is None]
    if unassigned:
        raise JobError(f"{', '.join(unassigned)}: a pool job takes NAME=value only")
    record = Job(
        id=f"{int(now * 1000):012x}-{secrets.token_hex(3)}",
        checkout=checkout,
        target=target,
        args=args,
        hold=hold,
        state=QUEUED,
        submitted_at=now,
    )
    with _locked(root):
        open_log(root, record.id).close()
        return _write(root, record)


def _registration(root: Path, runner: str) -> int:
    folder = ensure_queue(root) / "runners"
    return _shared_fd(folder / checked_name(runner), os.O_WRONLY)


def register(root: Path, runner: str) -> None:
    """
    Args:
        root: the queue directory.
        runner: the name of a pool runner that takes jobs from this queue.

    Raises:
        JobError: ``runner`` is no compose project name.
    """
    os.close(_registration(root, runner))


@contextlib.contextmanager
def serving(root: Path, runner: str) -> Iterator[None]:
    """Args:
        root: the queue directory.
        runner: the pool runner whose loop runs in this process.

    Yields:
        Once the runner is registered and its registration locked by this
        process, which holds the lock until the body ends or the process
        dies, however it dies.
    """
    fd = _registration(root, runner)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


@contextlib.contextmanager
def standing_in(root: Path, runner: str) -> Iterator[bool]:
    """Args:
        root: the queue directory.
        runner: a pool runner whose job the caller would end.

    Yields:
        Whether no process serves the queue as ``runner``; while it is
        True the caller holds the registration lock, so the runner cannot
        serve again before the body ends.
    """
    fd = _registration(root, runner)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True
    finally:
        os.close(fd)


def mark_failed(root: Path, runner: str, reason: str) -> None:
    """
    Args:
        root: the queue directory.
        runner: a registered pool runner.
        reason: why it takes no job, on one line; empty unmarks it.
    """
    fd = _registration(root, runner)
    try:
        os.ftruncate(fd, 0)
        os.write(fd, " ".join(reason.split()).encode())
    finally:
        os.close(fd)


def runners(root: Path) -> dict[str, str]:
    """Args:
        root: the queue directory.

    Returns:
        Every registered runner with its state: busy or held by its job,
        else failed while it is marked so, else idle.
    """
    folder = root / "runners"
    names = sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []
    states = {name: FAILED if failure(root, name) else IDLE for name in names}
    for record in jobs(root):
        if record.runner in states and record.state in (RUNNING, HELD):
            states[record.runner] = BUSY if record.state == RUNNING else HELD
    return states


def runner_rows(root: Path, now: float) -> list[dict[str, object]]:
    """Args:
        root: the queue directory.
        now: the current time.

    Returns:
        One row per registered runner: its state, whether a process serves
        the queue as it, the job it runs or holds with that job's stack, and
        how long it has held it; the row of a held job, and of a running job
        no process serves any longer, also names the command that releases it.
    """
    active = {
        record.runner: record
        for record in jobs(root)
        if record.state in (RUNNING, HELD)
    }
    rows: list[dict[str, object]] = []
    for name, state in runners(root).items():
        record = active.get(name)
        alive = is_serving(root, name)
        row: dict[str, object] = {
            "runner": name,
            "state": state,
            "serving": alive,
            "job": record.id if record else None,
            "stack": record.stack if record else None,
            "held_seconds": None,
        }
        if record is not None and state == HELD and record.ended_at is not None:
            row["held_seconds"] = int(now - record.ended_at)
        if record is not None and (state == HELD or not alive):
            row["release"] = RELEASE.format(id=record.id)
        if state == FAILED:
            row["reason"] = failure(root, name)
        rows.append(row)
    return rows


def claim(root: Path, runner: str, stack: str, now: float) -> Job | None:
    """Args:
        root: the queue directory.
        runner: the idle runner asking for work.
        stack: the compose project name of the runner's job stack.
        now: the claim time.

    Returns:
        The oldest queued job, now running on ``runner``; None when the runner is not idle or nothing waits.

    Raises:
        JobError: ``runner`` or ``stack`` is no compose project name.
    """
    checked_name(runner)
    checked_name(stack)
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
    return _end(root, job_id, exit_code, now, None)


def strand(root: Path, job_id: str, exit_code: int, now: float) -> Job:
    """Args:
        root: the queue directory.
        job_id: the running job whose stack may outlive it.
        exit_code: the deploy's exit status.
        now: the end time.

    Returns:
        The job, held whatever its hold, so its runner takes no job until
        ``make runner-release`` has removed the stack.
    """
    return _end(root, job_id, exit_code, now, True)


def end(root: Path, job_id: str, exit_code: int, now: float) -> Job:
    """Args:
        root: the queue directory.
        job_id: the running job, whose deploy left no stack: it never
            started, or its stack is removed and its runner gone.
        exit_code: the job's exit status.
        now: the end time.

    Returns:
        The job, done or failed by its exit status whatever its hold.
    """
    return _end(root, job_id, exit_code, now, False)


def _end(root: Path, job_id: str, exit_code: int, now: float, held: bool | None) -> Job:
    with _locked(root):
        record = job(root, job_id)
        if record.state != RUNNING:
            raise JobError(f"job {job_id} is {record.state}, not {RUNNING}")
        keep = record.hold if held is None else held
        state = HELD if keep else DONE if exit_code == 0 else FAILED
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
        fd = _regular_fd(log_path(root, job_id), os.O_RDONLY)
        with os.fdopen(fd, encoding="utf-8", errors="replace") as handle:
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
