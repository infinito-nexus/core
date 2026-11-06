"""Failure signature: a short digest of what a red run failed on, so a loop can
tell a repeat of the same failure from a new one without keeping the raw lines,
which may carry a credential.

The signed text is every failing JUnit case; else, for an Ansible run, the block
of the task it failed in and did not recover from (banner, cause and fatal
lines) plus the failing Playwright cases; else the failing Playwright cases;
else the failure lines ``failure_lines`` keeps; else the last log line. A hung
run signs the task it hangs in with its cause and fatal lines, else its last
line.

A Playwright case is its spec file and title, without ordinal, retry suffix or
duration, also when the deploy printed the report inside an escaped YAML
``msg`` folded over several lines; a case that passed on a retry is flaky, not
failing. Volatile parts (timestamps, clock times and Ansible command deltas,
durations, container and image ids, UUIDs, Ansible temp paths, ports, onion
hosts, ``/tmp/tmp*`` paths, epoch seconds, IPv4 addresses) are masked before
hashing, so two runs of the same failure share one signature.
"""

from __future__ import annotations

import hashlib
import re

from agents.routines.tools.junit import failures
from agents.routines.tools.log_scan import (
    failing_block,
    failure_lines,
    last_task_block,
    log_lines,
)

_VOLATILE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
    r"|\b\d{1,3}(?:\.\d{1,3}){3}\b"
    r"|\b[a-z2-7]{16,56}\.onion\b"
    r"|/tmp/tmp[\w-]+"
    r"|\b1[5-9]\d{8}\b"
    r"|:\d{4,5}\b"
    r"|\b\d+:\d{2}:\d{2}(?:[.,]\d+)?\b"
    r"|\bansible-tmp-[0-9.-]+"
    r"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    r"|\b[0-9a-f]{12,64}\b"
    r"|\b\d+(?:\.\d+)?\s?(?:ms|s)\b"
)
_FOLD = re.compile(r"\\\n\\")
_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
_PLAYWRIGHT_CASE = re.compile(
    r"([✘✓])\s+\d+\s+(?:\[[^\]]+\]\s+›\s+)?(\S+?):\d+:\d+\s+›\s+(.+?)"
    r"(?:\s+\(retry\s+#\d+\))?(?:\s+\(\d+(?:\.\d+)?m?s\))?\s*$"
)
_MASK = "<volatile>"
_DIGEST_LENGTH = 16


def _digest(text: str) -> str:
    if not text:
        return ""
    masked = " ".join(_VOLATILE.sub(_MASK, text).split())
    return hashlib.sha256(masked.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]


def _last_line(log: str) -> str:
    lines = log_lines(log)
    return lines[-1] if lines else ""


def _unescaped(log: str) -> list[str]:
    text = _FOLD.sub("", "\n".join(log_lines(log)))
    text = _UNICODE_ESCAPE.sub(lambda found: chr(int(found.group(1), 16)), text)
    return text.replace("\\n", "\n").replace('\\"', '"').splitlines()


def playwright_failures(log: str) -> list[str]:
    """Return the Playwright cases ``log`` reports as failing, each as
    ``<spec file> › <title>``, sorted: a case with a ``✘`` attempt and no ``✓``
    one. Reads plain report lines and a report escaped and folded inside a
    YAML ``msg``.

    Args:
        log: the run's log.
    """
    outcomes: dict[str, set[str]] = {}
    for line in _unescaped(log):
        found = _PLAYWRIGHT_CASE.search(line)
        if found:
            mark, spec, title = found.groups()
            outcomes.setdefault(f"{spec} › {title}", set()).add(mark)
    return sorted(case for case, marks in outcomes.items() if marks == {"✘"})


def _failure_text(log: str, junit_xml: str) -> str:
    cases = failures(junit_xml) if junit_xml else []
    if cases:
        return "\n".join(f"{case['name']}\n{case['message']}" for case in cases)
    specs = playwright_failures(log)
    block = failing_block(log)
    if block or specs:
        return "\n".join([*block, *specs])
    lines = failure_lines(log)
    if lines:
        return "\n".join(lines)
    return _last_line(log)


def failure_signature(log: str, junit_xml: str) -> str:
    """Return the digest of the failure a run shows, or ``""`` when the run
    left no text to sign.

    Args:
        log: the run's log.
        junit_xml: the run's JUnit report, ``""`` when it wrote none.
    """
    return _digest(_failure_text(log, junit_xml))


def hung_signature(log: str) -> str:
    """Return the digest of where a hung run stopped: the ``TASK`` banner it
    printed last with the cause and fatal lines after it, else its last line;
    ``""`` for an empty log.

    Args:
        log: the hung run's log.
    """
    return _digest("\n".join(last_task_block(log)) or _last_line(log))


def repeated(previous: list[str], current: str) -> bool:
    """Return whether ``current`` repeats the signature of the red run before.

    Two reds in a row that both left no text to sign (``""``) repeat too: the
    loop has nothing new to act on.

    Args:
        previous: the signatures of the earlier red runs, oldest first.
        current: the signature of this run.
    """
    return bool(previous) and previous[-1] == current
