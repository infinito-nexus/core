from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import TYPE_CHECKING

from cli.administration.deploy.pool.serve.__main__ import settings
from utils.runner import jobs
from utils.runner.loop import confined, copy_checkout

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import TextIO


def run(argv: list[str], env: Mapping[str, str], out: TextIO, err: TextIO) -> int:
    """
    Args:
        argv: the checkout of the job this runner holds or runs.
        env: the pool runner's environment, as :func:`settings` reads it.
        out: where the sync goes.
        err: where a refusal or a failed copy goes.

    Returns:
        0 once every file git sees in the checkout is copied over the
        runner's copy, which keeps its inode, so the held stack that mounts
        it sees the edit; 2 while the runner holds or runs no job or the
        checkout is no job checkout inside its roots; 1 for a failed copy.
    """
    parser = argparse.ArgumentParser(prog="pool sync")
    parser.add_argument("checkout")
    named = parser.parse_args(argv).checkout
    queue, runner = settings(env)
    checkout = confined(named, runner.roots)
    if checkout is None:
        print(f"[runner] {named!r} is no job checkout of {runner.name}", file=err)
        return 2
    if jobs.runners(queue).get(runner.name) not in (jobs.HELD, jobs.BUSY):
        print(f"[runner] {runner.name} holds no job to sync into", file=err)
        return 2
    try:
        copy_checkout(checkout, runner.checkout, runner.install)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"[runner] syncing {checkout} failed: {exc}", file=err)
        return 1
    print(f"[runner] synced {checkout} into {runner.checkout}", file=out)
    return 0


def main() -> int:
    return run(sys.argv[1:], os.environ, sys.stdout, sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
