"""Recognise a run that a newer run superseded: a cancellation triggered by a
label event or a newer push, shown as a red "Finish pipeline" step, is not a
failure. The routine waits for the superseding run instead of triaging it.
"""

from __future__ import annotations

import re

_SUPERSEDE = re.compile(
    r"higher priority waiting request"
    r"|superseded by (?:a )?newer"
    r"|cancel(?:l)?ed by a newer",
    re.IGNORECASE,
)

_RED = re.compile(
    r"✗|✘|×|##\[error\]|cancel(?:l)?ed|failed|failure",
    re.IGNORECASE,
)


def is_superseded(log: str) -> bool:
    """Return whether ``log`` is a run cancelled by a superseding run.

    True when the log both carries a supersession signal (a newer run took the
    concurrency slot) and shows the "Finish pipeline" step red; a red finish
    step without that signal is a genuine failure, not a superseded run.

    Args:
        log: the captured run log.
    """
    if not _SUPERSEDE.search(log):
        return False
    return any(
        "finish pipeline" in line.lower() and _RED.search(line)
        for line in log.splitlines()
    )
