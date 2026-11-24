from __future__ import annotations

import argparse
import sys
import time
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.runner.jobs import (
    HELD,
    RELEASE,
    JobError,
    QueueTimeoutError,
    follow,
    job,
    parse_duration,
    queue_root,
    submit,
    wait_until_started,
)
from utils.runner.role import queue_refusal

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import TextIO

POLL_SECONDS = 2.0
TRUE = "true"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Submit a deploy target to the local runner pool and follow it."
    )
    parser.add_argument("target")
    parser.add_argument("assignments", nargs="*")
    parser.add_argument("--hold", choices=(TRUE, "false"), default="false")
    parser.add_argument("--timeout", default="")
    return parser


def run(
    argv: list[str],
    root: Path,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    out: TextIO,
    err: TextIO,
) -> int:
    """Submit one job, wait for a runner, follow its log and return its status.

    Args:
        argv: the target, its make assignments, ``--hold`` and ``--timeout``.
        root: the queue directory.
        clock: returns the current time.
        sleep: waits the given seconds.
        out: where the job id, the queue position and the job's log go.
        err: where a refusal or a withdrawal goes.
    """
    args = _parser().parse_args(argv)
    try:
        timeout = parse_duration(args.timeout) if args.timeout else None
    except JobError as exc:
        print(f"[runner] timeout= {exc}", file=err)
        return 2
    refusals = queue_refusal(root)
    if refusals:
        print("\n".join(refusals), file=err)
        return 2
    try:
        record = submit(
            root,
            str(PROJECT_ROOT),
            args.target,
            args.assignments,
            args.hold == TRUE,
            clock(),
        )
    except JobError as exc:
        print(f"[runner] {exc}", file=err)
        return 2
    command = " ".join(["make", args.target, *args.assignments])
    print(f"[runner] job {record.id} submitted: {command}", file=out, flush=True)
    try:
        wait_until_started(root, record.id, timeout, clock, sleep, out, POLL_SECONDS)
    except QueueTimeoutError as exc:
        print(f"[runner] {exc}", file=err)
        return 1
    status = follow(root, record.id, out, sleep, POLL_SECONDS)
    if job(root, record.id).state == HELD:
        print(
            f"[runner] job {record.id} is held; release it with "
            + RELEASE.format(id=record.id),
            file=out,
        )
    return status


def main() -> int:
    return run(
        sys.argv[1:], queue_root(), time.time, time.sleep, sys.stdout, sys.stderr
    )


if __name__ == "__main__":
    sys.exit(main())
