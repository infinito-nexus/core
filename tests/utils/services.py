"""Helpers for suites whose checks talk to a deployed service.

A check that reaches a service needs two things this module supplies: a way to
say whether the service answers at all, and a way to report progress while it
works. Progress goes to a file rather than stdout because pytest captures at
file-descriptor level and releases only after the test ends, so a long run
would otherwise sit silent. The file lands under ``build/`` so an operator can
follow it from the host while the suite runs inside the stack's container,
which has a ``/tmp`` of its own.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

REACHABLE_TIMEOUT = 5


def progress_log(suite: str) -> Path:
    """Return the file a suite appends its progress to.

    Args:
        suite: the suite's name, used as the file's stem.
    """
    return PROJECT_ROOT / "build" / f"{suite}.log"


def progress(suite: str, message: str) -> None:
    """Append one status line, flushed, so ``tail -f`` shows it immediately.

    A failure to write is swallowed: status reporting must never turn a green
    suite red.

    Args:
        suite: the suite's name, selecting the log file.
        message: the line to append, without a trailing newline.
    """
    stamp = time.strftime("%H:%M:%S")
    path = progress_log(suite)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message}\n")
    except OSError:
        pass


def answers(url: str) -> bool:
    """Return whether something serves ``url`` right now.

    Args:
        url: an endpoint that responds without authentication.
    """
    try:
        with urllib.request.urlopen(  # noqa: S310 - this repository's own service definitions
            url, timeout=REACHABLE_TIMEOUT
        ):
            return True
    except (urllib.error.URLError, OSError):
        return False
