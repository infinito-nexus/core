from __future__ import annotations

import contextlib
import dataclasses
import errno
import fcntl
import json
import os
import re
import stat
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import TextIO

QUEUED = "queued"
RUNNING = "running"
HELD = "held"
DONE = "done"
FAILED = "failed"
ENDED = (DONE, FAILED)
STATES = (QUEUED, RUNNING, HELD, *ENDED)
QUEUE_ROOT_MODE = 0o3770
SHARED_DIR_MODE = 0o2770
SHARED_FILE_MODE = 0o660
QUEUE_DIRS = ("jobs", "logs", "runners")

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


def checked_id(job_id: str) -> str:
    """Args:
        job_id: a job id as :func:`utils.runner.jobs.submit` makes it.

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
