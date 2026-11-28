from __future__ import annotations

import argparse
import subprocess
import sys
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.runner import jobs
from utils.runner.role import docker_host, pool_job

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path
    from typing import TextIO

    Probe = Callable[[Sequence[str]], subprocess.CompletedProcess]

SYNC = (
    'cd "$RUNNER_SRC_DIR" && PYTHONPATH="$RUNNER_SRC_DIR" '
    'exec python3 -m cli.administration.deploy.pool.sync "$1"'
)


def resync(record: jobs.Job, root: Path) -> list[str]:
    """Args:
        record: a held or running job whose record names its runner's own stack.
        root: the queue directory, which holds the socket of the infra
            runner's daemon.

    Returns:
        The call that copies the job's checkout into the runner's copy
        again, inside the runner, which mounts both.
    """
    return [
        "env",
        f"DOCKER_HOST={docker_host(root)}",
        "docker",
        "exec",
        record.runner,
        "sh",
        "-c",
        SYNC,
        "sync",
        record.checkout,
    ]


def run(argv: list[str], root: Path, probe: Probe, out: TextIO, err: TextIO) -> int:
    """
    Args:
        argv: ``--sync`` or nothing, then the job id.
        root: the queue directory.
        probe: runs a command and returns it completed.
        out: where the Docker host and the stack name go, one per line, for
            ``scripts/meta/env/load.sh`` to export as ``DOCKER_HOST`` and
            ``INFINITO_STACK_NAME``.
        err: where a refusal goes.

    Returns:
        0 once both lines are printed, or with ``--sync`` once the job's
        checkout is copied into its runner's copy again, for a held or
        running job whose record names its runner's own job stack; 2 for an
        unusable queue, no such job, a job in any other state or a foreign
        stack, printing nothing; else the exit status of the failed copy.
    """
    parser = argparse.ArgumentParser(prog="make <target> job=<id>")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("job")
    args = parser.parse_args(argv)
    record, refusals = pool_job(root, args.job)
    if record is None:
        print("\n".join(refusals), file=err)
        return 2
    if args.sync:
        return probe(resync(record, root)).returncode
    print(docker_host(root), file=out)
    print(record.stack, file=out)
    return 0


def _probe(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), cwd=PROJECT_ROOT, check=False)


def main() -> int:
    return run(sys.argv[1:], jobs.queue_root(), _probe, sys.stdout, sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
