"""Log scanning: pull the failing line out of a job log, and confirm from a CI
job log that a named change actually ran. A Playwright spec prefixes a run with
``✓`` and a skipped one with ``-``; a change whose only trace is a skipped line
did not run.
"""

from __future__ import annotations

import re

_FAILURE = re.compile(
    r"^.*(?:\bFAILED\b|\bFAIL\b|\bERROR\b|AssertionError|Traceback|✗|✘|× ).*$",
    re.MULTILINE,
)
_SKIPPED = re.compile(r"(?:^\s*[-–]\s)|(?:\bskip(?:ped)?\b)", re.IGNORECASE)
_RAN = ("✓", "✔", "passed", "pass")


def failing_line(log: str) -> str | None:
    """Return the first line of ``log`` that signals a failure, stripped, or
    ``None`` when the log shows none.

    Args:
        log: the captured job or test log.
    """
    match = _FAILURE.search(log)
    return match.group().strip() if match else None


def change_ran(log: str, marker: str) -> str | None:
    """Return the first line of ``log`` that proves ``marker`` ran, or ``None``.

    A proving line carries the marker and a run token (``✓``/passed) and is not
    a skip line; a line that only skips the marker (a leading ``-`` or the word
    ``skipped``) does not count, so a guarded spec reported as skipped is not
    mistaken for executed.

    Args:
        log: the CI job log to read.
        marker: the spec name, env key or command text whose run to confirm.
    """
    for line in log.splitlines():
        if marker not in line or _SKIPPED.search(line):
            continue
        if any(token in line.lower() for token in _RAN):
            return line.strip()
    return None
