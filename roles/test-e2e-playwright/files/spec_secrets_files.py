from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

import spec_secrets

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

TEMP = ".masked."
OPEN_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
CREATE_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
PUBLISHED_DIR = 0o755


def open_root(root: Path) -> int | None:
    """Open a reports dir without following a link.

    Args:
        root: the directory.

    Returns:
        Its descriptor, or None when it is missing.

    Raises:
        SpecSecretsError: it is a link or no directory.
    """
    try:
        return os.open(root, spec_secrets.OPEN_DIR)
    except FileNotFoundError:
        return None
    except OSError:
        raise spec_secrets.SpecSecretsError(
            f"{root} is a link or no directory, it is not masked"
        ) from None


def walk(root: Path, failed: list[Exception]) -> Iterator[tuple[int, str]]:
    """List the files below a directory, never following a link.

    Args:
        root: the directory; a missing one holds nothing.
        failed: collects the errors of directories that cannot be read.

    Yields:
        Per file, ``TEMP`` ones included, its open directory until the next one.
    """

    def unreadable(error: OSError) -> None:
        if not isinstance(error, FileNotFoundError):
            failed.append(error)

    top = open_root(root)
    if top is None:
        return
    try:
        for _here, _dirs, files, at in os.fwalk(".", onerror=unreadable, dir_fd=top):
            for name in files:
                yield at, name
    finally:
        os.close(top)


def open_file(at: int, name: str) -> int | None:
    """Open a regular file of a directory without following a link.

    Args:
        at: the open directory.
        name: the file's name in it.

    Returns:
        Its descriptor, or None when it is gone, a link or no regular file.
    """
    try:
        if not stat.S_ISREG(os.stat(name, dir_fd=at, follow_symlinks=False).st_mode):
            return None
        descriptor = os.open(name, OPEN_FILE, dir_fd=at)
    except FileNotFoundError:
        return None
    except OSError as error:
        if error.errno == errno.ELOOP:
            return None
        raise
    if stat.S_ISREG(os.fstat(descriptor).st_mode):
        return descriptor
    os.close(descriptor)
    return None


def swap(at: int, name: str, mode: int, fill: Callable[[BinaryIO], object]) -> None:
    """Write a ``TEMP`` sibling of a name, then rename it over the name.

    Args:
        at: the open directory that holds the name.
        name: the name; a FIFO, device or hard link there is replaced, unopened.
        mode: the exact mode the file gets once written.
        fill: writes the file's bytes into the open sibling.
    """
    temp = f"{TEMP}{os.urandom(8).hex()}"
    written = os.open(temp, CREATE_FILE, 0o600, dir_fd=at)
    try:
        with os.fdopen(written, "wb") as target:
            fill(target)
            target.flush()
            os.fchmod(target.fileno(), mode)
        os.replace(temp, name, src_dir_fd=at, dst_dir_fd=at)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp, dir_fd=at)


def open_dir(name: str | Path, at: int | None = None) -> int:
    """Open one directory of the published reports, created when missing, never through a link.

    Args:
        name: its name in ``at``, or the reports dir itself.
        at: the open parent directory, None for the reports dir.

    Returns:
        Its descriptor, set to exactly ``PUBLISHED_DIR``, created or reused, so
        no setgid bit of a parent or an earlier run and no umask is left, and
        locked while open, so it waits for any other masker publishing into
        it; the ``TEMP`` regular files left in it then belong to a killed
        masker and are removed.

    Raises:
        OSError: it is a link or no directory, or its parent is missing.
    """
    with contextlib.suppress(FileExistsError):
        os.mkdir(name, PUBLISHED_DIR, dir_fd=at)
    descriptor = os.open(name, spec_secrets.OPEN_DIR, dir_fd=at)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.fchmod(descriptor, PUBLISHED_DIR)
        with os.scandir(descriptor) as entries:
            files = [e.name for e in entries if e.is_file(follow_symlinks=False)]
        for temp in (name for name in files if name.startswith(TEMP)):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp, dir_fd=descriptor)
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


def open_into(root: int, here: str) -> int:
    """Open the directory a published file goes into, one component at a time.

    Args:
        root: the open reports dir.
        here: the file's directory, relative to it.

    Returns:
        The open directory; ``open_dir`` created or reused each component
        relative to the one before, so no link on the way is followed.
    """
    into = os.dup(root)
    for part in Path(here).parts:
        try:
            inner = open_dir(part, into)
        finally:
            os.close(into)
        into = inner
    return into
