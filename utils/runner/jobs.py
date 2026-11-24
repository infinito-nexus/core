from __future__ import annotations

import contextlib
import dataclasses
import errno
import fcntl
import json
import os
import re
import secrets
import stat
import sys
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
STATES = (QUEUED, RUNNING, HELD, *ENDED)
IDLE = "idle"
BUSY = "busy"
RELEASE = "make runner-release job={id}"
QUEUE_ROOT_MODE = 0o3770
SHARED_DIR_MODE = 0o2770
SHARED_FILE_MODE = 0o660
QUEUE_DIRS = ("jobs", "logs", "runners")

_DURATION = re.compile(r"^\s*(\d+)\s*([smhd])\s*$")
_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_ID = re.compile(r"[0-9a-f]{12,}-[0-9a-f]{6}")
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
_TARGET = re.compile(r"[a-z0-9][a-z0-9-]*")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
_SAFE = os.O_NOFOLLOW | os.O_NONBLOCK
_UNSAFE = (errno.ELOOP, errno.ENXIO)
_NONE = type(None)
_NUMBER = (int, float)
_FIELDS: dict[str, tuple[type, ...]] = {
    "id": (str,),
    "checkout": (str,),
    "target": (str,),
    "args": (list,),
    "hold": (bool,),
    "state": (str,),
    "submitted_at": _NUMBER,
    "runner": (str, _NONE),
    "stack": (str, _NONE),
    "started_at": (*_NUMBER, _NONE),
    "ended_at": (*_NUMBER, _NONE),
    "exit_code": (int, _NONE),
}
_SKIPPED: set[str] = set()


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
    """Returns:
    The machine-wide queue every checkout submits to: ``jobs`` below the
    cache base the paths SPOT names.
    """
    return machine() / "jobs"


def checked_id(job_id: str) -> str:
    """Args:
        job_id: a job id as :func:`submit` makes it.

    Returns:
        The id.

    Raises:
        JobError: it is no job id, so it could name a path outside the queue.
    """
    if _ID.fullmatch(job_id) is None:
        raise JobError(f"{job_id!r} is no job id")
    return job_id


def checked_name(name: str) -> str:
    """Args:
        name: a runner name or a job stack, both compose project names.

    Returns:
        The name.

    Raises:
        JobError: it is no compose project name.
    """
    if _NAME.fullmatch(name) is None:
        raise JobError(f"{name!r} is no runner or stack name")
    return name


def _jobs(root: Path) -> Path:
    return root / "jobs"


def log_path(root: Path, job_id: str) -> Path:
    """
    Args:
        root: the queue directory.
        job_id: the job.

    Raises:
        JobError: ``job_id`` is no job id.
    """
    return root / "logs" / f"{checked_id(job_id)}.log"


def _shared_dir(path: Path, mode: int) -> Path:
    try:
        path.mkdir(mode=mode)
    except FileExistsError:
        return path
    path.chmod(mode)
    return path


def ensure_queue(root: Path) -> Path:
    """Args:
        root: the queue directory.

    Returns:
        The queue, created where it is missing with the layout svc-runner
        deploys: the root sticky and group-shared, so only an entry's owner
        renames or removes it, and ``jobs``, ``logs`` and ``runners``
        group-shared below it. An existing entry keeps its mode.
    """
    _shared_dir(root, QUEUE_ROOT_MODE)
    for name in QUEUE_DIRS:
        _shared_dir(root / name, SHARED_DIR_MODE)
    return root


def layout_problems(root: Path) -> list[str]:
    """Args:
        root: an existing queue directory this user may search.

    Returns:
        Every way a job of the pool could swap a directory of the queue
        under its users: the root lacks the sticky bit, or ``jobs``,
        ``logs`` or ``runners`` is missing, a link, no directory, or owned
        by another user than the root; nothing for a sound layout.
    """
    owner = root.stat()
    problems = []
    if not owner.st_mode & stat.S_ISVTX:
        problems.append(f"{root} lacks the sticky bit")
    for name in QUEUE_DIRS:
        path = root / name
        try:
            entry = os.lstat(path)
        except FileNotFoundError:
            problems.append(f"{path} is missing")
            continue
        if not stat.S_ISDIR(entry.st_mode):
            problems.append(f"{path} is a link or no directory")
        elif entry.st_uid != owner.st_uid:
            problems.append(
                f"{path} belongs to uid {entry.st_uid}, not to uid "
                f"{owner.st_uid}, which owns the queue"
            )
    return problems


def _irregular(path: Path) -> JobError:
    return JobError(f"{path} is no regular file; the queue does not open it")


def _regular_fd(path: Path, flags: int) -> int:
    try:
        fd = os.open(path, flags | _SAFE)
    except OSError as exc:
        if exc.errno in _UNSAFE:
            raise _irregular(path) from exc
        raise
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise _irregular(path)
    os.set_blocking(fd, True)
    return fd


def _new_fd(path: Path, flags: int) -> int:
    fd = os.open(path, flags | os.O_CREAT | os.O_EXCL | _SAFE, SHARED_FILE_MODE)
    os.fchmod(fd, SHARED_FILE_MODE)
    os.set_blocking(fd, True)
    return fd


def _shared_fd(path: Path, flags: int) -> int:
    try:
        return _new_fd(path, flags)
    except FileExistsError:
        return _regular_fd(path, flags)


def open_log(root: Path, job_id: str) -> TextIO:
    """Args:
        root: the queue directory.
        job_id: the job.

    Returns:
        The job's log, opened for appending; created group-writable, so the
        submitter and every pool runner can write it.

    Raises:
        JobError: the log is a link, a FIFO or anything else but a regular file.
    """
    log = log_path(root, job_id)
    ensure_queue(root)
    fd = _shared_fd(log, os.O_WRONLY | os.O_APPEND)
    return os.fdopen(fd, "a", encoding="utf-8")


@contextlib.contextmanager
def _locked(root: Path) -> Iterator[None]:
    ensure_queue(root)
    fd = _shared_fd(root / ".lock", os.O_WRONLY | os.O_APPEND)
    with os.fdopen(fd, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _write(root: Path, job: Job) -> Job:
    folder = _jobs(ensure_queue(root))
    staged = folder / f".{checked_id(job.id)}.json"
    staged.unlink(missing_ok=True)
    try:
        fd = _new_fd(staged, os.O_WRONLY)
    except FileExistsError as exc:
        raise JobError(f"{staged} reappeared while the queue wrote it") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(dataclasses.asdict(job), handle, sort_keys=True)
    staged.replace(folder / f"{job.id}.json")
    return job


def _of(value: object, kinds: tuple[type, ...]) -> bool:
    return isinstance(value, kinds) and (bool in kinds or not isinstance(value, bool))


def _record(raw: object, path: Path) -> Job:
    if not isinstance(raw, dict) or set(raw) != set(_FIELDS):
        raise JobError(f"{path} holds no job record of the fields {', '.join(_FIELDS)}")
    malformed = {key for key, kinds in _FIELDS.items() if not _of(raw[key], kinds)}
    if raw["state"] not in STATES:
        malformed.add("state")
    if not isinstance(raw["target"], str) or _TARGET.fullmatch(raw["target"]) is None:
        malformed.add("target")
    if not isinstance(raw["args"], list) or not all(
        isinstance(arg, str) and _ASSIGNMENT.fullmatch(arg) for arg in raw["args"]
    ):
        malformed.add("args")
    if malformed:
        raise JobError(f"{path} holds a malformed {', '.join(sorted(malformed))}")
    return Job(**{**raw, "args": tuple(raw["args"])})


def _read(path: Path) -> Job:
    with os.fdopen(_regular_fd(path, os.O_RDONLY), encoding="utf-8") as handle:
        try:
            raw = json.load(handle)
        except ValueError as exc:
            raise JobError(f"{path} holds no job record: {exc}") from exc
    record = _record(raw, path)
    if record.id != path.stem:
        raise JobError(f"{path} holds job {record.id!r}, not the job of its name")
    checked_id(record.id)
    for name in (record.runner, record.stack):
        if name is not None:
            checked_name(name)
    return record


def _skip(path: Path, reason: Exception) -> None:
    line = f"[runner] skipped {path}: {reason}"
    if line not in _SKIPPED:
        _SKIPPED.add(line)
        print(line, file=sys.stderr, flush=True)


def jobs(root: Path) -> list[Job]:
    """Args:
        root: the queue directory.

    Returns:
        Every job record, oldest submission first. A record withdrawn while
        it is read is gone; any other record that cannot be read as a job
        is left out and named once per process on stderr.
    """
    folder = _jobs(root)
    if not folder.is_dir():
        return []
    found: list[Job] = []
    for path in folder.glob("*.json"):
        if path.name.startswith("."):
            continue
        try:
            found.append(_read(path))
        except FileNotFoundError:
            continue
        except (JobError, OSError) as exc:
            _skip(path, exc)
    return sorted(found, key=lambda job: (job.submitted_at, job.id))


def job(root: Path, job_id: str) -> Job:
    """Args:
        root: the queue directory.
        job_id: the job.

    Raises:
        JobError: ``job_id`` is no job id, no such job, or its record is no job.
    """
    path = _jobs(root) / f"{checked_id(job_id)}.json"
    try:
        return _read(path)
    except FileNotFoundError as exc:
        raise JobError(f"no job {job_id} in {root}") from exc


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


def failure(root: Path, runner: str) -> str:
    """Args:
        root: the queue directory.
        runner: a pool runner.

    Returns:
        Why the runner is marked failed, empty while it is not.
    """
    try:
        fd = _regular_fd(root / "runners" / checked_name(runner), os.O_RDONLY)
    except (FileNotFoundError, JobError):
        return ""
    with os.fdopen(fd, encoding="utf-8") as handle:
        return handle.read().strip()


def is_serving(root: Path, runner: str) -> bool:
    """Args:
        root: the queue directory.
        runner: a registered pool runner.

    Returns:
        Whether a process serves the queue as ``runner`` right now.
    """
    try:
        fd = _regular_fd(root / "runners" / checked_name(runner), os.O_RDONLY)
    except (FileNotFoundError, JobError):
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


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
