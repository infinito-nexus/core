from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from cli.administration.deploy.runner.command import RUNNER_ROLE
from cli.administration.infra.__main__ import RUNNER_DOWN
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.runner.jobs import HELD, JobError, cleanup_report, queue_root

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from pathlib import Path
    from typing import TextIO

    from utils.runner.jobs import Job

    Probe = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

INFRA = (sys.executable, "-m", "cli.administration.infra")
RUNNER_STATE = (*INFRA, "running")
PROJECTS = (*INFRA, "docker", "compose", "ls", "--all", "--format", "json")
ORPHAN = "orphan"


def project_prefix(root: Path) -> str:
    """Args:
        root: repository root.

    Returns:
        The compose project prefix svc-runner gives the job stack of each pool runner.
    """
    services = load_yaml(root / "roles" / RUNNER_ROLE / ROLE_FILE_META_SERVICES)
    return services["runner"]["project_prefix"]


def job_stacks(listing: str, prefix: str) -> list[str]:
    """Args:
        listing: what ``docker compose ls --all --format json`` prints inside the infra runner.
        prefix: the compose project prefix of the pool's job stacks.

    Returns:
        Every compose project named ``<prefix>-<N>``, the job stack of pool runner N.
    """
    pattern = re.compile(rf"{re.escape(prefix)}-[0-9]+")
    return sorted(
        row["Name"] for row in json.loads(listing) if pattern.fullmatch(row["Name"])
    )


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
            f"docker compose ls inside the infra runner failed (rc={listed.returncode}): "
            f"{listed.stderr.strip()}"
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
    root: Path, prefix: str, probe: Probe, now: float, out: TextIO, err: TextIO
) -> int:
    """Args:
        root: the queue directory.
        prefix: the compose project prefix of the pool's job stacks.
        probe: runs a command and returns it completed, with its output as text.
        now: the current time.
        out: where one JSON object per held job and orphaned stack goes.
        err: where a failure to read the job stacks goes.

    Returns:
        0 once every row is printed, 2 when the job stacks cannot be read.
    """
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
        project_prefix(PROJECT_ROOT),
        _probe,
        time.time(),
        sys.stdout,
        sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
