from __future__ import annotations

import contextlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

TREE = "tree"
REMOTE_PREVIEW = "<ssh mktemp -d>"
_REMOTE_DIR = re.compile(r"(/[A-Za-z0-9_][A-Za-z0-9._-]*){2,}")


def preview(prefix: str) -> Path:
    """The shape of a stage :func:`private` would create, creating nothing.

    Args:
        prefix: the stage name's prefix.
    """
    return Path(tempfile.gettempdir()) / f"{prefix}XXXXXXXX"


def _retry_writable(function, path: str, error: BaseException) -> None:
    """Make the parent of *path* owner-writable and retry the removal once.

    Args:
        function: the ``os.unlink`` or ``os.rmdir`` call that failed.
        path: the entry it failed on.
        error: what it raised; anything but a PermissionError is re-raised.
    """
    if not isinstance(error, PermissionError) or function not in (
        os.unlink,
        os.rmdir,
    ):
        raise error
    parent = Path(path).parent
    parent.chmod(parent.stat().st_mode | stat.S_IRWXU)
    function(path)


def remove(stage: Path) -> None:
    """Delete *stage*, warning instead of raising when that fails.

    Args:
        stage: the directory to delete.
    """
    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(stage, onexc=_retry_writable)
        else:
            shutil.rmtree(
                stage,
                onerror=lambda func, path, info: _retry_writable(func, path, info[1]),
            )
    except OSError as error:
        print(
            f"# recover: WARNING the stage {stage} was not removed, remove it "
            f"by hand: {error}",
            file=sys.stderr,
        )


@contextlib.contextmanager
def private(prefix: str) -> Iterator[Path]:
    """An owner-only local directory under a random name, removed on exit.

    Args:
        prefix: the stage name's prefix.
    """
    stage = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield stage
    finally:
        remove(stage)


def remote_private(host: str) -> str | None:
    """Create an owner-only directory on *host* with its own ``mktemp -d``.

    Args:
        host: ``[user@]host`` reached over ssh.

    Returns:
        The directory, or None when it could not be created or ``mktemp``
        answered something that is not a plain absolute path below ``/``;
        the reason, with ssh's own stderr, then goes to stderr.
    """
    created = subprocess.run(
        ["ssh", host, "mktemp", "-d"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    directory = created.stdout.strip()
    if created.returncode != 0:
        print(
            f"# recover: ssh {host} mktemp -d exited {created.returncode}: "
            f"{created.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    if not _REMOTE_DIR.fullmatch(directory):
        print(
            f"# recover: ssh {host} mktemp -d answered {directory!r}, "
            "which is no plain absolute path",
            file=sys.stderr,
        )
        return None
    return directory


def remote_remove(host: str, directory: str) -> None:
    """Delete *directory* on *host*, warning instead of raising when that fails.

    Args:
        host: ``[user@]host`` reached over ssh.
        directory: a directory :func:`remote_private` created.
    """
    if subprocess.run(
        ["ssh", host, "rm", "-rf", "--", directory],
        stdin=subprocess.DEVNULL,
        check=False,
    ).returncode:
        print(
            f"# recover: WARNING the stage {directory} on {host} was not removed, "
            "remove it by hand",
            file=sys.stderr,
        )
