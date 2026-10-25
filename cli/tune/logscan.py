"""Scan an Ansible deploy log for optimisation signals, deterministically.

The tuner routine calls this instead of eyeballing a log. ``profile_tasks``
prints a timestamp line AFTER each task whose ``(H:MM:SS.mmm)`` is the duration
of the task whose header came before it, so a header is paired with the next
timestamp line. Aggregating by role and task name turns a per-item loop into a
count: forty-nine two-second rows under one task name is the per-item spawn
pattern the tuner batches away.

Usage: ``python -m cli.tune.logscan <deploy.log> [--top N]``.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

HEADER = re.compile(r"^(?:TASK|RUNNING HANDLER) \[(?P<label>.+?)\]\s*\**\s*$")
DURATION = re.compile(r"\((?P<h>\d+):(?P<m>\d\d):(?P<s>\d\d\.\d+)\)")
RETRYING = re.compile(r"FAILED - RETRYING: \[?(?P<item>.+?)[\]:]")


def _seconds(match: re.Match) -> float:
    return int(match["h"]) * 3600 + int(match["m"]) * 60 + float(match["s"])


def task_durations(text: str) -> list[tuple[str, str, float]]:
    """Return ``(role, task, seconds)`` for every task the log timed.

    ``profile_tasks`` prints its timestamp line when the NEXT task starts, so
    the ``(H:MM:SS.mmm)`` printed after header N is the duration of header
    N-1's task. The duration is therefore booked to the previous header, not
    the current one; the line is doubled by two callbacks, so only the first
    after each header is read; the last task's duration appears only in the
    run's RECAP and is not captured here.

    ``role`` is the text before the first `` : `` in the task label (the empty
    string when the label has none); ``task`` is the remainder.

    Args:
        text: the whole deploy log.
    """
    out: list[tuple[str, str, float]] = []
    current: str | None = None
    previous: str | None = None
    booked = False
    for line in text.splitlines():
        header = HEADER.match(line)
        if header:
            current = header["label"]
            booked = False
            continue
        duration = DURATION.search(line)
        if duration and current is not None and not booked:
            if previous is not None:
                role, _, task = previous.partition(" : ")
                out.append((role if task else "", task or role, _seconds(duration)))
            previous = current
            booked = True
    return out


def aggregate(durations: list[tuple[str, str, float]]) -> list[tuple[str, int, float]]:
    """Return ``(label, count, total_seconds)`` per task, slowest total first.

    A high ``count`` on one label is a per-item loop: the tuner batches it.
    """
    totals: dict[str, list[float]] = defaultdict(list)
    for role, task, seconds in durations:
        totals[f"{role} : {task}" if role else task].append(seconds)
    rows = [(label, len(times), sum(times)) for label, times in totals.items()]
    return sorted(rows, key=lambda row: row[2], reverse=True)


def retries(text: str) -> dict[str, int]:
    """Return a count of ``FAILED - RETRYING`` lines per item: a wait that hides
    a failure rather than slowness."""
    counts: dict[str, int] = defaultdict(int)
    for line in text.splitlines():
        hit = RETRYING.search(line)
        if hit:
            counts[hit["item"].strip()] += 1
    return dict(counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cli.tune.logscan")
    parser.add_argument("log")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args(argv)
    text = Path(args.log).read_text(
        encoding="utf-8", errors="ignore"
    )  # nocheck: cache-read
    rows = aggregate(task_durations(text))
    print(f"# slowest {min(args.top, len(rows))} tasks (count x each = loop)")
    for label, count, total in rows[: args.top]:
        marker = "  <- per-item loop" if count >= 5 else ""
        print(f"{total:8.1f}s  x{count:<4} {label}{marker}")
    rt = retries(text)
    if rt:
        print("\n# retries (a wait that hides a failure)")
        for item, count in sorted(rt.items(), key=lambda kv: kv[1], reverse=True):
            print(f"  {count}x {item}")
    return 0


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    sample = (
        "TASK [web-app-keycloak : create client] *****\n"
        "Samstag 24 Oktober 2026  11:09:00 +0200 (0:00:00.050)   0:00:00.050 ***\n"
        "Samstag 24 Oktober 2026  11:09:00 +0200 (0:00:00.050)   0:00:00.049 ***\n"
        "ok: [host]\n"
        "TASK [web-app-keycloak : configure realm] *****\n"
        "Samstag 24 Oktober 2026  11:09:07 +0200 (0:00:07.000)   0:00:07.050 ***\n"
        "Samstag 24 Oktober 2026  11:09:07 +0200 (0:00:07.000)   0:00:07.049 ***\n"
        "ok: [host]\n"
        "RUNNING HANDLER [openresty : reload] *****\n"
        "Samstag 24 Oktober 2026  11:09:09 +0200 (0:00:02.000)   0:00:09.050 ***\n"
        "Samstag 24 Oktober 2026  11:09:09 +0200 (0:00:02.000)   0:00:09.049 ***\n"
        "ok: [host]\n"
        "FAILED - RETRYING: [localhost]: wait for marker (3 retries left).\n"
    )
    durations = task_durations(sample)
    top = {label: (count, total) for label, count, total in aggregate(durations)}
    _expect(top["web-app-keycloak : create client"] == (1, 7.0), top)
    _expect(top["web-app-keycloak : configure realm"] == (1, 2.0), top)
    _expect("openresty : reload" not in top, top)
    _expect(retries(sample) == {"localhost": 1}, retries(sample))
    print("logscan self-check ok")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _demo()
    else:
        raise SystemExit(main())
