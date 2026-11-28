"""Log scanning: pull the failing line out of a job log, confirm from a CI job
log that a named change actually ran, and tell whether a red run got as far as
the changed code. A Playwright spec prefixes a run with ``✓`` and a skipped one
with ``-``; a change whose only trace is a skipped line did not run.

Ansible output is read as the repository's callback writes it: ANSI colour
codes, an act ``[workflow/job]   | `` prefix under act, a ``TASK [...]`` banner
per task, an ``[ERROR]: Task failed:`` cause line before the
``fatal: [host]: FAILED! =>`` line, and the result as a YAML body after it. A
task that ends with ``...ignoring`` failed without stopping the run, and a
``FAILED - RETRYING`` line is a retry the task may still pass. A run that ended
red (a ``PLAY RECAP`` with a failed or unreachable host; without a recap, a
non-zero exit line) is decided by its last fatal, even when ``always:`` tasks
or handlers ran after it; otherwise a fatal that a later ``TASK`` banner
follows was rescued, and only the failures after the last banner decide.
"""

from __future__ import annotations

import re

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_ACT = re.compile(r"^\[[^\]]+\]\s+\|\s?")
_FAILURE = re.compile(
    r"^.*(?:\bFAILED\b|\bFAIL\b|\bERROR\b|AssertionError|Traceback|✗|✘|× ).*$",
    re.MULTILINE,
)
_SKIPPED = re.compile(r"(?:^\s*[-–]\s)|(?:\bskip(?:ped)?\b)", re.IGNORECASE)
_RAN = ("✓", "✔", "passed", "pass")
_RETRYING = re.compile(r"\bFAILED - RETRYING\b")
_IGNORING = "...ignoring"
_BANNER = re.compile(r"^(?:TASK|RUNNING HANDLER) \[")
_FATAL = re.compile(r"^(?:fatal|failed): \[|^\[ERROR\]: ")
_RECAP = "PLAY RECAP"
_RECAP_FAILED = re.compile(r"\b(?:failed|unreachable)=[1-9]")
_EXIT_STATUS = (
    re.compile(r"^\[ERROR\] ansible-playbook exited with status (\d+)$"),
    re.compile(r"^make(?:\[\d+\])?: \*\*\* \[.*\] Error (\d+)$"),
)
_SCRIPT_ENDED = re.compile(r"^✅ Script ended at\b")
_FAILED_RECAP = "failed recap"


def log_lines(log: str) -> list[str]:
    """Return the non-empty lines of ``log`` in output order, ANSI colour codes
    and the act ``[workflow/job]   |`` prefix with its trailing space stripped,
    surrounding whitespace cut.

    Args:
        log: a run's log.
    """
    return [
        stripped
        for raw in log.splitlines()
        if (stripped := _ACT.sub("", _ANSI.sub("", raw).strip()).strip())
    ]


def _recap_failed(lines: list[str]) -> bool | None:
    recaps = [index for index, line in enumerate(lines) if line.startswith(_RECAP)]
    if not recaps:
        return None
    return any(_RECAP_FAILED.search(line) for line in lines[recaps[-1] :])


def _exit_status(lines: list[str]) -> str | None:
    for line in reversed(lines):
        for pattern in _EXIT_STATUS:
            found = pattern.match(line)
            if found:
                return found.group(1)
        if _SCRIPT_ENDED.match(line):
            return "0"
    return _FAILED_RECAP if _recap_failed(lines) else None


def run_status(log: str) -> str | None:
    """Return how the run ended, or ``None`` while nothing in ``log`` says it
    did: the status of the deploy wrapper's ``[ERROR] ansible-playbook exited
    with status <n>`` line or of a ``make: *** [...] Error <n>`` line, ``"0"``
    after the deploy's ``✅ Script ended at`` line, ``"failed recap"`` after a
    ``PLAY RECAP`` with a failed or unreachable host. A ``PLAY RECAP`` without
    one may close one play of several, so it is no end.

    Args:
        log: the run's log in output order.
    """
    return _exit_status(log_lines(log))


def run_exited(log: str) -> bool:
    """Return whether ``log`` shows that the run ended (``run_status``).

    Args:
        log: the run's log in output order.
    """
    return run_status(log) is not None


def _ignored(lines: list[str]) -> set[int]:
    dropped: set[int] = set()
    banner = 0
    for index, line in enumerate(lines):
        if _BANNER.match(line):
            banner = index
        elif line == _IGNORING:
            dropped.update(range(banner, index + 1))
    return dropped


def _banners(lines: list[str]) -> list[int]:
    return [index for index, line in enumerate(lines) if _BANNER.match(line)]


def _deciding_banner(lines: list[str], fatal: list[int]) -> int:
    banners = _banners(lines)
    recap_failed = _recap_failed(lines)
    red = (
        _exit_status(lines) not in (None, "0") if recap_failed is None else recap_failed
    )
    if fatal and red:
        before = [index for index in banners if index < fatal[-1]]
        return before[-1] if before else -1
    return banners[-1] if banners else -1


def _fatal_indexes(lines: list[str]) -> list[int]:
    ignored = _ignored(lines)
    fatal = [
        index
        for index, line in enumerate(lines)
        if _FATAL.match(line) and index not in ignored
    ]
    start = _deciding_banner(lines, fatal)
    return [index for index in fatal if index > start]


def _failing_indexes(lines: list[str]) -> list[int]:
    ignored = _ignored(lines)
    banners = _banners(lines)
    start = banners[-1] if banners else -1
    return [
        index
        for index, line in enumerate(lines)
        if index > start
        and _FAILURE.search(line)
        and not _RETRYING.search(line)
        and index not in ignored
    ]


def _banner_text(line: str) -> str:
    return line.rstrip("*").rstrip()


def failure_lines(log: str) -> list[str]:
    """Return every line of ``log`` that signals a failure the run did not get
    past, in output order, ANSI codes stripped.

    An Ansible ``FAILED - RETRYING`` line, every line of a task that ends with
    ``...ignoring`` and, in an Ansible log, every line before the last ``TASK``
    banner (a traceback a passed task printed) are left out.

    Args:
        log: the run's log in output order.
    """
    lines = log_lines(log)
    return [lines[index] for index in _failing_indexes(lines)]


def _block(lines: list[str], start: int, fatal: list[int]) -> list[str]:
    head = [_banner_text(lines[start])] if start >= 0 else []
    return head + sorted(lines[index] for index in fatal)


def failing_block(log: str) -> list[str]:
    """Return the block of the Ansible task the run failed in and did not
    recover from: its ``TASK`` banner, trailing stars cut, then its ``[ERROR]:``
    cause and ``fatal``/``failed`` lines, sorted so the order in which hosts
    finished does not count; ``[]`` when no such task failed, as after a
    rescued fatal in a run that did not end red.

    Args:
        log: the run's log in output order.
    """
    lines = log_lines(log)
    fatal = _fatal_indexes(lines)
    if not fatal:
        return []
    banners = [index for index in _banners(lines) if index < fatal[0]]
    return _block(lines, banners[-1] if banners else -1, fatal)


def last_task(log: str) -> str:
    """Return the ``TASK`` banner the run printed last, trailing stars cut, or
    ``""`` when it printed none: the task a hung run hangs in.

    Args:
        log: the run's log in output order.
    """
    block = last_task_block(log)
    return block[0] if block else ""


def last_task_block(log: str) -> list[str]:
    """Return the ``TASK`` banner the run printed last, trailing stars cut,
    with the cause and fatal lines printed after it, sorted; ``[]`` when it
    printed no banner: where a hung or stopped run stands.

    Args:
        log: the run's log in output order.
    """
    lines = log_lines(log)
    banners = _banners(lines)
    if not banners:
        return []
    ignored = _ignored(lines)
    fatal = [
        index
        for index, line in enumerate(lines)
        if index > banners[-1] and _FATAL.match(line) and index not in ignored
    ]
    return _block(lines, banners[-1], fatal)


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


def _carries(lines: list[str], marker: str) -> bool:
    return any(marker in line and not _SKIPPED.search(line) for line in lines)


def mentions(log: str, marker: str) -> bool:
    """Return whether any line of ``log`` other than a skip line carries
    ``marker``: the reach of a hung run, which has no failure to end at.

    Args:
        log: the run's log in output order.
        marker: the text the first output line of the changed code carries.
    """
    return _carries(log_lines(log), marker)


def reached(log: str, marker: str) -> bool:
    """Return whether the run reached ``marker`` before its last failure.

    The run reached it when a line carrying the marker, other than a skip line,
    comes before or on the end line: in an Ansible log (one with a ``TASK``
    banner) the last deciding ``fatal``/``failed`` or ``[ERROR]:`` cause line,
    never a rescued fatal or a noise line a passed task printed; in another
    log the last of ``failure_lines``; the last line when the log has neither.
    A run whose every failure came first, or that only skipped the marker, did
    not.

    Args:
        log: the run's log in output order.
        marker: the text the first output line of the changed code carries (a
            task name, a spec title, a workflow step name).
    """
    lines = log_lines(log)
    ansible = bool(_banners(lines))
    anchors = _fatal_indexes(lines) if ansible else _failing_indexes(lines)
    end = anchors[-1] if anchors else len(lines) - 1
    return _carries(lines[: end + 1], marker)
