from __future__ import annotations

import argparse
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from cli.administration.deploy.pool import teardown
from utils import PROJECT_ROOT
from utils.runner import jobs
from utils.runner.loop import ABANDONED
from utils.runner.role import docker_host, pool_job

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path
    from typing import TextIO

    Probe = Callable[[Sequence[str]], subprocess.CompletedProcess]


def removal(stack: str, root: Path) -> list[str]:
    """Args:
        stack: the compose project of a held job's stack.
        root: the queue directory, which holds the socket of that daemon.

    Returns:
        The call that removes it on the infra runner's own daemon, which the
        pool runners use as theirs, through the socket svc-runner opens to
        the runner-queue group in the queue.
    """
    return ["env", f"DOCKER_HOST={docker_host(root)}", *teardown(stack)]


def _release_held(
    root: Path, record: jobs.Job, probe: Probe, out: TextIO, err: TextIO
) -> int:
    removed = probe(removal(record.stack, root))
    if removed.returncode != 0:
        print(
            f"[runner] removing stack {record.stack} of job {record.id} failed "
            f"(rc={removed.returncode}); the job stays held on {record.runner}",
            file=err,
        )
        return removed.returncode
    jobs.release(root, record.id)
    print(
        f"[runner] job {record.id} released: stack {record.stack} removed, "
        f"{record.runner} takes jobs again",
        file=out,
    )
    return 0


def _abandon(
    root: Path,
    record: jobs.Job,
    probe: Probe,
    clock: Callable[[], float],
    out: TextIO,
    err: TextIO,
) -> int:
    with jobs.standing_in(root, record.runner) as gone:
        if not gone:
            print(
                f"[runner] job {record.id} is {jobs.RUNNING} on {record.runner}, "
                "which still serves the queue; nothing to release",
                file=err,
            )
            return 2
        removed = probe(removal(record.stack, root))
        if removed.returncode != 0:
            print(
                f"[runner] removing stack {record.stack} of job {record.id} failed "
                f"(rc={removed.returncode}); the job stays {jobs.RUNNING} on "
                f"{record.runner}",
                file=err,
            )
            return removed.returncode
        with jobs.open_log(root, record.id) as handle:
            print(
                f"[runner] job {record.id} abandoned: {record.runner} no longer "
                "serves the queue; it does not run again",
                file=handle,
            )
        jobs.end(root, record.id, ABANDONED, clock())
    print(
        f"[runner] job {record.id} failed with {ABANDONED}: {record.runner} no "
        f"longer serves the queue, stack {record.stack} removed",
        file=out,
    )
    return 0


def run(
    argv: list[str],
    root: Path,
    probe: Probe,
    clock: Callable[[], float],
    out: TextIO,
    err: TextIO,
) -> int:
    """
    Args:
        argv: the job id.
        root: the queue directory.
        probe: runs a command and returns it completed.
        clock: returns the current time.
        out: where the release goes.
        err: where a refusal or a failed removal goes.

    Returns:
        0 once the stack is gone and the job ended: a held job by its exit
        status with its runner idle again, a running job whose runner no
        longer serves the queue failed with 137; 2 for an unwritable queue,
        no such job, a job in any other state, a running job whose runner
        still serves the queue, or a record whose stack is not its runner's
        own job stack; else the exit status of the failed removal, with the
        job left as it was.
    """
    parser = argparse.ArgumentParser(prog="make runner-release")
    parser.add_argument("job")
    record, refusals = pool_job(root, parser.parse_args(argv).job)
    if record is None:
        print("\n".join(refusals), file=err)
        return 2
    try:
        if record.state == jobs.RUNNING:
            return _abandon(root, record, probe, clock, out, err)
        return _release_held(root, record, probe, out, err)
    except jobs.JobError as exc:
        print(f"[runner] {exc}", file=err)
        return 2


def _probe(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), cwd=PROJECT_ROOT, check=False)


def main() -> int:
    return run(
        sys.argv[1:], jobs.queue_root(), _probe, time.time, sys.stdout, sys.stderr
    )


if __name__ == "__main__":
    sys.exit(main())
