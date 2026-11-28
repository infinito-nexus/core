from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from cli.administration.infra.__main__ import RUNNER_DOWN
from utils import PROJECT_ROOT
from utils.infra_inventory import POOL_KEY, POOL_ROLE, infra_roles
from utils.preflight.networks import PROJECT_LABEL
from utils.runner.jobs import HELD, JobError, cleanup_report, queue_root
from utils.runner.role import project_prefix, queue_refusal, runner_stack

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from pathlib import Path
    from typing import TextIO

    from utils.runner.jobs import Job

    Probe = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

INFRA = (sys.executable, "-m", "cli.administration.infra")
RUNNER_STATE = (*INFRA, "running")
PROJECTS = (
    *INFRA,
    "docker",
    "ps",
    "--all",
    "--filter",
    f"label={PROJECT_LABEL}",
    "--format",
    f'{{{{.Label "{PROJECT_LABEL}"}}}}',
)
ORPHAN = "orphan"


def job_stacks(listing: str, prefix: str) -> list[str]:
    """Args:
        listing: the compose project of every container, running or not, one
            per line, as :data:`PROJECTS` prints them inside the infra runner.
        prefix: the compose project prefix of the pool's job stacks.

    Returns:
        Every compose project that is the job stack of a pool runner.
    """
    return sorted({name for name in listing.split() if runner_stack(name, prefix)})


def existing_stacks(probe: Probe, prefix: str) -> list[str]:
    """Args:
        probe: runs a command and returns it completed, with its output as text.
        prefix: the compose project prefix of the pool's job stacks.

    Returns:
        The job stacks the infra runner's Docker lists, none while the runner is down.

    Raises:
        JobError: the runner's state or its compose projects cannot be read.
    """
    state = probe(RUNNER_STATE)
    if state.returncode == RUNNER_DOWN:
        return []
    if state.returncode != 0:
        raise JobError(
            f"the infra runner's state is unknown (rc={state.returncode}): "
            f"{state.stderr.strip()}"
        )
    listed = probe(PROJECTS)
    if listed.returncode != 0:
        raise JobError(
            f"listing the compose projects inside the infra runner failed "
            f"(rc={listed.returncode}): {listed.stderr.strip()}"
        )
    return job_stacks(listed.stdout, prefix)


def report_rows(
    held: Iterable[tuple[Job, float]], orphans: Iterable[str]
) -> list[dict[str, object]]:
    """Args:
        held: every held job with its age in seconds.
        orphans: every job stack no running or held job owns.

    Returns:
        One row per held job, then one per orphaned stack.
    """
    rows: list[dict[str, object]] = [
        {
            "kind": HELD,
            "job": record.id,
            "runner": record.runner,
            "stack": record.stack,
            "checkout": record.checkout,
            "age_seconds": int(age),
        }
        for record, age in held
    ]
    rows.extend({"kind": ORPHAN, "stack": name} for name in orphans)
    return rows


def run(
    root: Path,
    prefix: str,
    env: Mapping[str, str],
    probe: Probe,
    now: float,
    out: TextIO,
    err: TextIO,
) -> int:
    """Args:
        root: the queue directory.
        prefix: the compose project prefix of the pool's job stacks.
        env: environment holding the pool's opt-in.
        probe: runs a command and returns it completed, with its output as text.
        now: the current time.
        out: where one JSON object per held job and orphaned stack goes.
        err: where a refusal, the pool being off or a failure to read the job
            stacks goes.

    Returns:
        0 once every row is printed, or with no row while the pool is off;
        2 for an opt-in other than true or false, while this user cannot use
        the queue, or when the job stacks cannot be read.
    """
    try:
        pool_on = POOL_ROLE in infra_roles(env)
    except ValueError as exc:
        print(str(exc), file=err)
        return 2
    if not pool_on:
        print(
            f"[runner-cleanup-report] the runner pool is off ({POOL_KEY} is not "
            "true): no held job or job stack to report",
            file=err,
        )
        return 0
    refusals = queue_refusal(root)
    if refusals:
        print("\n".join(refusals), file=err)
        return 2
    try:
        stacks = existing_stacks(probe, prefix)
    except JobError as exc:
        print(f"[runner-cleanup-report] {exc}", file=err)
        return 2
    held, orphans = cleanup_report(root, stacks, now)
    for row in report_rows(held, orphans):
        print(json.dumps(row, sort_keys=True), file=out)
    return 0


def _probe(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
    )


def main() -> int:
    return run(
        queue_root(),
        project_prefix(),
        os.environ,
        _probe,
        time.time(),
        sys.stdout,
        sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
