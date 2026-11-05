"""Parse and audit the output of one write-continuity checker run."""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

INTERVAL_S = 0.2
TIMEOUT_S = 1
_RECORD = re.compile(r"(?:^|\|\s*)(start|ack|fail|present|done)\b(.*)$")


@dataclass
class CheckerRun:
    run_id: str = ""
    started_ms: int | None = None
    acks: dict[int, int] = field(default_factory=dict)
    fails: dict[int, int] = field(default_factory=dict)
    present: set[int] = field(default_factory=set)
    done: bool = False


def parse_checker_output(text: str) -> CheckerRun:
    run = CheckerRun()
    for line in text.splitlines():
        match = _RECORD.search(line.strip())
        if not match:
            continue
        kind, rest = match.group(1), match.group(2).split()
        try:
            if kind == "start" and len(rest) == 2:
                run.run_id, run.started_ms = rest[0], int(rest[1])
            elif kind in ("ack", "fail") and len(rest) == 2:
                target = run.acks if kind == "ack" else run.fails
                target[int(rest[0])] = int(rest[1])
            elif kind == "present" and len(rest) == 1:
                run.present.add(int(rest[0]))
            elif kind == "done" and not rest:
                run.done = True
        except ValueError:
            continue
    return run


_PROBE = re.compile(r"(?:^|\|\s*)probe(-done|\s+(\S+)\s+(\S.*?))\s*$")


def parse_probe_output(text: str) -> tuple[bool, dict[str, str]]:
    """Return ``(done, records)`` of one probe service's log.

    The probe prints ``probe <key> <value>`` per result and ``probe-done`` last.
    """
    done, records = False, {}
    for line in text.splitlines():
        match = _PROBE.search(line.strip())
        if not match:
            continue
        if match.group(1) == "-done":
            done = True
        else:
            records[match.group(2)] = match.group(3)
    return done, records


def audit(run: CheckerRun) -> list[int]:
    """Return every acknowledged sequence number missing from the engine."""
    return sorted(seq for seq in run.acks if seq not in run.present)


def acks_between(run: CheckerRun, start_ms: int, end_ms: int) -> list[int]:
    """Return the sequence numbers acknowledged in ``[start_ms, end_ms]``."""
    return sorted(seq for seq, at in run.acks.items() if start_ms <= at <= end_ms)


def max_write_gap_s(run: CheckerRun) -> float:
    """Return the longest stretch in seconds without an acknowledged write.

    The stretch is measured between consecutive acknowledgements, and also from
    the run start to the first one and from the last one to the last attempt.
    """
    if not run.acks:
        return float("inf")
    stamps = sorted(run.acks.values())
    events = [*run.acks.values(), *run.fails.values()]
    edges = [stamps[0] - (run.started_ms if run.started_ms is not None else stamps[0])]
    edges += [b - a for a, b in itertools.pairwise(stamps)]
    edges.append(max(events) - stamps[-1])
    return max(edges) / 1000.0
