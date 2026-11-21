#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import fcntl
import os
import re
import select
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

PARENT = Path("/tmp/infinito-playwright-spec-secrets")  # noqa: S108 - open_owned refuses it unless it is a 0700 dir of the runner, never followed
PREFIX = "run."
KEY = re.compile(r"[A-Z][A-Z0-9_]*")
NAME_MAX = 255
BREAKS = re.compile(
    "[\r\x0b\x0c\x1c\x1d\x1e\x85\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}]"
)
RENDERED = ".rendered"
DIR_MODE = 0o700
FILE_MODE = 0o400
POLL_SECONDS = 1
OPEN_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
USAGE = "prune | create <hold seconds> <owner pid> | split <run dir>"


class SpecSecretsError(Exception):
    pass


def parse(text: str) -> dict[str, str]:
    """Map the rendered ``KEY=VALUE`` lines, naming a bad line by number only.

    Args:
        text: the rendered ``templates/playwright.secrets.j2``.

    Returns:
        Every key with its value, in template order. Lines end at ``\\n`` only;
        blank lines and lines starting with ``#`` are skipped.
    """
    entries: dict[str, str] = {}
    for number, line in enumerate(text.split("\n"), start=1):
        if BREAKS.search(line):
            raise SpecSecretsError(f"line {number} holds a line break other than LF")
        if not line.strip() or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not KEY.fullmatch(key) or len(key) > NAME_MAX:
            raise SpecSecretsError(
                f"line {number} is not KEY=VALUE with KEY matching {KEY.pattern}"
                f" in at most {NAME_MAX} characters"
            )
        if key in entries:
            raise SpecSecretsError(f"line {number} repeats an earlier key")
        entries[key] = value
    return entries


def open_owned(name: Path | str, dir_fd: int | None = None) -> int:
    """Open a directory without following a link, refusing one others can reach.

    Args:
        name: the directory, relative to ``dir_fd`` when one is given.
        dir_fd: an open directory to look ``name`` up in.

    Returns:
        The open descriptor of the accepted directory.
    """
    try:
        descriptor = os.open(name, OPEN_DIR, dir_fd=dir_fd)
    except OSError as error:
        raise SpecSecretsError(f"{name} is not a directory: {error.strerror}") from None
    info = os.fstat(descriptor)
    problem = ""
    if info.st_uid != os.geteuid():
        problem = f"{name} is owned by uid {info.st_uid}, not {os.geteuid()}"
    elif stat.S_IMODE(info.st_mode) != DIR_MODE:
        problem = (
            f"{name} has mode {stat.S_IMODE(info.st_mode):04o}, expected {DIR_MODE:04o}"
        )
    if problem:
        os.close(descriptor)
        raise SpecSecretsError(problem)
    return descriptor


def prune() -> int:
    """Remove every run directory below ``PARENT`` that no live run locks.

    Returns:
        The number removed. A missing or foreign ``PARENT`` removes nothing.
    """
    if not os.path.lexists(PARENT):
        return 0
    removed = 0
    parent = open_owned(PARENT)
    try:
        fcntl.flock(parent, fcntl.LOCK_EX)
        for name in os.listdir(parent):
            if not name.startswith(PREFIX):
                continue
            try:
                child = open_owned(name, dir_fd=parent)
            except SpecSecretsError:
                continue
            try:
                fcntl.flock(child, fcntl.LOCK_EX | fcntl.LOCK_NB)
                shutil.rmtree(PARENT / name)
                removed += 1
            except BlockingIOError:
                continue
            finally:
                os.close(child)
    finally:
        os.close(parent)
    return removed


def hold(directory: Path, seconds: int, owner: int | None) -> None:
    """Keep the inherited lock in a detached child while the run lasts.

    Args:
        directory: the locked run directory.
        seconds: the longest the child keeps the lock, 0 for no limit.
        owner: a pidfd of the process that owns the run, or None; once that
            process ends, the child removes the directory.
    """
    if os.fork():
        return
    try:
        os.setsid()
        null = os.open(os.devnull, os.O_RDWR)
        for stream in (0, 1, 2):
            os.dup2(null, stream)
        deadline = time.monotonic() + seconds if seconds else float("inf")
        watched = [] if owner is None else [owner]
        while time.monotonic() < deadline and os.path.lexists(directory):
            if select.select(watched, [], [], POLL_SECONDS)[0]:
                shutil.rmtree(directory, ignore_errors=True)
                break
    finally:
        os._exit(0)


def create(seconds: int, owner: int) -> Path:
    """Create a locked run directory below ``PARENT``.

    Args:
        seconds: the longest a detached child keeps the lock, 0 for no limit.
        owner: the pid whose end makes the child remove the directory, 0 for
            none. With both 0 no child is left and the lock ends with this call.

    Returns:
        The new directory, mode 0700.
    """
    watched = None
    if owner:
        try:
            watched = os.pidfd_open(owner)
        except OSError:
            raise SpecSecretsError(f"owner pid {owner} is not running") from None
    try:
        with contextlib.suppress(FileExistsError):
            PARENT.mkdir(mode=DIR_MODE)
        try:
            parent = open_owned(PARENT)
        except SpecSecretsError as error:
            raise SpecSecretsError(
                f"{error}; remove it with rm -rf -- {PARENT} so the next run"
                " recreates it"
            ) from None
        try:
            fcntl.flock(parent, fcntl.LOCK_SH)
            name = Path(tempfile.mkdtemp(prefix=PREFIX, dir=PARENT)).name
            held = open_owned(name, dir_fd=parent)
            fcntl.flock(held, fcntl.LOCK_SH)
        finally:
            os.close(parent)
        if seconds or watched is not None:
            hold(PARENT / name, seconds, watched)
        os.close(held)
    finally:
        if watched is not None:
            os.close(watched)
    return PARENT / name


def write(run: int, entries: dict[str, str]) -> None:
    """Write each value to a file named after its key, readable by its owner only.

    Args:
        run: the descriptor of the accepted run directory.
        entries: the parsed keys and values.
    """
    for key, value in entries.items():
        try:
            descriptor = os.open(
                key,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                FILE_MODE,
                dir_fd=run,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                os.fchmod(handle.fileno(), FILE_MODE)
                handle.write(value)
        except OSError as error:
            raise SpecSecretsError(f"writing a file failed: {error.strerror}") from None


def open_run(directory: Path) -> int:
    """Open a run directory below ``PARENT`` without following a link.

    Args:
        directory: the run directory.

    Returns:
        The open descriptor of the accepted run directory.
    """
    if directory.parent != PARENT or not directory.name.startswith(PREFIX):
        raise SpecSecretsError(f"{directory} is not a run directory below {PARENT}")
    parent = open_owned(PARENT)
    try:
        return open_owned(directory.name, dir_fd=parent)
    finally:
        os.close(parent)


def split(directory: Path) -> int:
    """Turn the rendered template in a run directory into one file per key.

    Args:
        directory: a run directory below ``PARENT`` holding ``.rendered``.

    Returns:
        The number of files written. Once the directory is accepted,
        ``.rendered`` is gone afterwards, also on failure; a refused one is
        not touched.
    """
    run = open_run(directory)
    try:
        try:
            with os.fdopen(
                os.open(RENDERED, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=run), "rb"
            ) as handle:
                text = handle.read().decode("utf-8")
        except UnicodeDecodeError:
            raise SpecSecretsError("the rendered file is not UTF-8") from None
        except OSError as error:
            raise SpecSecretsError(f"{RENDERED}: {error.strerror}") from None
        entries = parse(text)
        write(run, entries)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(RENDERED, dir_fd=run)
        os.close(run)
    return len(entries)


def main(argv: list[str]) -> int:
    """Run one command and report paths or counts, never a key or a value.

    Args:
        argv: the program name and ``prune``, ``create <hold seconds> <owner
            pid>`` (not both 0) or ``split <run dir>``.

    Returns:
        0 on success and on a prune that skips a foreign ``PARENT``, 1 on a
        refused template or directory, 2 on bad usage.
    """
    command = argv[1:]
    bounds = command[1:] if command[:1] == ["create"] else []
    try:
        if command == ["prune"]:
            try:
                removed = prune()
            except SpecSecretsError as error:
                print(f"spec secrets prune skipped: {error}")
                return 0
            print(f"spec secrets removed: {removed}" if removed else "nothing to prune")
        elif (
            len(bounds) == 2 and all(map(str.isdigit, bounds)) and any(map(int, bounds))
        ):
            print(create(int(bounds[0]), int(bounds[1])))
        elif len(command) == 2 and command[0] == "split":
            print(f"spec secrets files written: {split(Path(command[1]))}")
        else:
            print(f"usage: {argv[0]} {USAGE}", file=sys.stderr)
            return 2
    except SpecSecretsError as error:
        print(f"spec secrets refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
