from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from utils.runner.jobs import JobError, follow, submit, wait_until_started

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from typing import TextIO

QUEUE_KEY = "INFINITO_RUNNER_QUEUE_DIR"
RUNNER_KEY = "INFINITO_POOL_RUNNER_NAME"
SRC_KEY = "RUNNER_SRC_DIR"
KEYS = (QUEUE_KEY, RUNNER_KEY, SRC_KEY)
POLL_SECONDS = 2.0
REFUSED = 2


def run(
    argv: list[str],
    env: Mapping[str, str],
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    out: TextIO,
    err: TextIO,
) -> int:
    """Submit one deploy target pinned to the pool runner a Semaphore runner serves and follow it.

    Args:
        argv: the deploy target and its ``NAME=value`` assignments.
        env: the Semaphore task's environment: the job queue
            (:data:`QUEUE_KEY`), the pool runner the job is pinned to
            (:data:`RUNNER_KEY`) and the checkout it deploys from
            (:data:`SRC_KEY`).
        clock: returns the current time.
        sleep: waits the given seconds.
        out: where the job id, the queue position and the job's log go.
        err: where a refusal goes.

    Returns:
        The job's exit status, or :data:`REFUSED` when a key is unset, no
        target is given or the queue refuses the job.
    """
    missing = [key for key in KEYS if not (env.get(key) or "").strip()]
    if missing or not argv:
        print(
            f"[runner] a pinned job needs a target and {', '.join(missing or KEYS)}",
            file=err,
        )
        return REFUSED
    root = Path(env[QUEUE_KEY])
    try:
        record = submit(
            root, env[SRC_KEY], argv[0], argv[1:], False, clock(), pin=env[RUNNER_KEY]
        )
    except JobError as exc:
        print(f"[runner] {exc}", file=err)
        return REFUSED
    command = " ".join(["make", *argv])
    print(
        f"[runner] job {record.id} pinned to {record.pin} submitted: {command}",
        file=out,
        flush=True,
    )
    wait_until_started(root, record.id, None, clock, sleep, out, POLL_SECONDS)
    return follow(root, record.id, out, sleep, POLL_SECONDS)


def main() -> int:
    return run(sys.argv[1:], os.environ, time.time, time.sleep, sys.stdout, sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
