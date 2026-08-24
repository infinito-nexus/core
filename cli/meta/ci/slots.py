"""Derive the deploy-chunk budget of one CI workflow run.

Usage:
  python -m cli.meta.ci.slots [--matrix] [--format json] [--field <name>]

A *chunk* is one serial block of deploy jobs in the orchestrator. Two
independent ceilings bound it, and the smaller one wins:

* **Queue clock.** GitHub cancels a job that sat queued for
  ``INFINITO_CI_QUEUE_HOURS``. With ``INFINITO_CI_CONCURRENCY`` runners free
  and every job assumed to burn its full ``timeout-minutes``, a chunk drains
  in waves, and the last wave that still starts inside the queue window is
  ``floor(queue_hours / job_timeout)``. A chunk therefore holds at most
  ``concurrency * waves`` jobs. Assuming every job runs to its timeout is
  deliberately pessimistic -- no job can outlast it -- so the drain estimate
  can only overshoot, never undershoot.

* **Run job cap.** GitHub caps a workflow run at ``INFINITO_CI_JOB_LIMIT``
  matrix jobs, counted across the whole run. Every non-deploy job the
  orchestrator chain spawns eats into that budget, so this module statically
  and CONSERVATIVELY counts them:

  - every orchestrator job reserves its full job count -- reusable workflows
    are opened and summed, static matrices multiplied out, dynamic
    (``fromJson``) matrices estimated at ``_DYNAMIC_MATRIX_ESTIMATE``;
  - the chunk blocks themselves reserve only their static jobs (the discover
    step); their dynamic per-row matrices are exactly the slots being
    budgeted.

  The worst entry point (``entry-*.yml``) adds its own jobs to the same run
  before calling the orchestrator; that overhead is subtracted too.

What is left is :func:`available`, the rows one sweep can deploy. It is spent
by :func:`chunk_count` blocks of :func:`chunk_size` rows. Because the
orchestrator cannot generate a variable number of jobs, the block count is
also capped by ``INFINITO_CI_MAX_CHUNKS``, the number of chunk blocks the
workflow YAML actually declares; a sweep that would need more rows than those
blocks hold leaves the rest to the next sweep's offset.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import TYPE_CHECKING

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.env.parser import env_setting

if TYPE_CHECKING:
    from pathlib import Path

_ORCHESTRATOR = ".github/workflows/call-orchestrator.yml"
_DEPLOY_WORKFLOW = ".github/workflows/call-test-deploy.yml"
_DEPLOY_JOB = "deploy"
_CHUNK_JOB_PREFIX = "test-deploy-chunk-"
_DYNAMIC_MATRIX_ESTIMATE = 5


def setting(key: str) -> int:
    """One integer CI setting, read through the shared env SPOT."""
    return int(env_setting(key))


def _load_workflow(path: Path) -> dict:
    data = load_yaml_any(str(path), default_if_missing={}) or {}
    return data if isinstance(data, dict) else {}


def _jobs(workflow: dict) -> dict:
    jobs = workflow.get("jobs")
    return jobs if isinstance(jobs, dict) else {}


def _matrix_size(job: dict) -> int:
    matrix = (job.get("strategy") or {}).get("matrix")
    if matrix is None:
        return 1
    if not isinstance(matrix, dict):
        return _DYNAMIC_MATRIX_ESTIMATE
    if any(isinstance(v, str) and "${{" in v for v in matrix.values()):
        return _DYNAMIC_MATRIX_ESTIMATE
    include = matrix.get("include")
    size = len(include) if isinstance(include, list) else 0
    axes = [
        len(values)
        for key, values in matrix.items()
        if key not in ("include", "exclude") and isinstance(values, list)
    ]
    if axes:
        size += math.prod(axes)
    return max(size, 1)


def _is_dynamic_matrix(job: dict) -> bool:
    matrix = (job.get("strategy") or {}).get("matrix")
    if matrix is None:
        return False
    if not isinstance(matrix, dict):
        return True
    return any(isinstance(v, str) and "${{" in v for v in matrix.values())


def _job_slots(repo_root: Path, job: dict, *, count_dynamic: bool) -> int:
    uses = job.get("uses")
    if isinstance(uses, str) and uses.startswith("./"):
        path = repo_root / uses.removeprefix("./")
        if not path.is_file():
            return 1
        return sum(
            _job_slots(repo_root, nested, count_dynamic=count_dynamic)
            for nested in _jobs(_load_workflow(path)).values()
        )
    if _is_dynamic_matrix(job) and not count_dynamic:
        return 0
    return _matrix_size(job)


def job_timeout_minutes(repo_root: Path | None = None) -> int:
    """The deploy job's own ``timeout-minutes``, read straight out of the
    workflow so the wave arithmetic cannot drift from the value CI enforces."""
    root = repo_root or PROJECT_ROOT
    job = _jobs(_load_workflow(root / _DEPLOY_WORKFLOW)).get(_DEPLOY_JOB) or {}
    timeout = job.get("timeout-minutes")
    if not isinstance(timeout, int):
        raise SystemExit(
            f"{_DEPLOY_WORKFLOW}: job {_DEPLOY_JOB!r} declares no integer "
            f"'timeout-minutes'; the chunk size is derived from it."
        )
    return timeout


def waves(repo_root: Path | None = None) -> int:
    """Runner waves that still start inside the queue window. Floored at 1:
    a job timeout at or above the window means one wave, never zero."""
    window = setting("INFINITO_CI_QUEUE_HOURS") * 60
    return max(window // job_timeout_minutes(repo_root), 1)


def chunk_size(repo_root: Path | None = None) -> int:
    """Rows one chunk may hold before its tail risks the queue cancel."""
    return setting("INFINITO_CI_CONCURRENCY") * waves(repo_root)


def reserved_breakdown(repo_root: Path | None = None) -> list[tuple[str, int]]:
    """Per orchestrator job: the job count it reserves in the run budget.
    Chunk blocks contribute only their static jobs (the discover step); their
    dynamic per-row matrices are the budgeted slots themselves."""
    root = repo_root or PROJECT_ROOT
    jobs = _jobs(_load_workflow(root / _ORCHESTRATOR))
    return [
        (
            name,
            _job_slots(root, job, count_dynamic=not name.startswith(_CHUNK_JOB_PREFIX)),
        )
        for name, job in jobs.items()
    ]


def reserved_slots(repo_root: Path | None = None) -> int:
    return sum(count for _, count in reserved_breakdown(repo_root))


def entry_overhead(repo_root: Path | None = None) -> int:
    """Worst-case jobs an ``entry-*.yml`` adds to the run around its
    orchestrator call (the orchestrator's own jobs are already counted)."""
    root = repo_root or PROJECT_ROOT
    orchestrator_path = root / _ORCHESTRATOR
    orchestrator_file = orchestrator_path.name
    totals = [0]
    for path in sorted(orchestrator_path.parent.iterdir()):
        if not (path.name.startswith("entry-") and path.name.endswith(".yml")):
            continue
        totals.append(
            sum(
                _job_slots(root, job, count_dynamic=True)
                for job in _jobs(_load_workflow(path)).values()
                if orchestrator_file not in str(job.get("uses", ""))
            )
        )
    return max(totals)


def available(repo_root: Path | None = None) -> int:
    """Deploy rows one run may spend across all its chunks."""
    limit = setting("INFINITO_CI_JOB_LIMIT")
    return max(limit - reserved_slots(repo_root) - entry_overhead(repo_root), 1)


def chunk_count(repo_root: Path | None = None) -> int:
    """Chunk blocks a sweep fills, capped by the blocks the YAML declares."""
    needed = math.ceil(available(repo_root) / chunk_size(repo_root))
    return max(min(needed, setting("INFINITO_CI_MAX_CHUNKS")), 1)


def rows_per_sweep(repo_root: Path | None = None) -> int:
    """Rows one sweep covers: the chunk blocks it fills, bounded by the run
    job cap. Rows beyond this roll into the next sweep via its offset."""
    return min(chunk_count(repo_root) * chunk_size(repo_root), available(repo_root))


def budget(repo_root: Path | None = None) -> dict[str, int]:
    return {
        "reserved": reserved_slots(repo_root),
        "entry_overhead": entry_overhead(repo_root),
        "available": available(repo_root),
        "job_timeout_minutes": job_timeout_minutes(repo_root),
        "waves": waves(repo_root),
        "chunk_size": chunk_size(repo_root),
        "chunk_count": chunk_count(repo_root),
        "rows_per_sweep": rows_per_sweep(repo_root),
    }


def render_matrix() -> str:
    """The budget as a CLI table: per-job reservations, then the totals and
    the chunk arithmetic they leave room for."""
    breakdown = reserved_breakdown()
    rows = [
        *breakdown,
        ("reserved", reserved_slots()),
        ("entry overhead (worst entry-*.yml)", entry_overhead()),
        ("job limit (INFINITO_CI_JOB_LIMIT)", setting("INFINITO_CI_JOB_LIMIT")),
        ("available", available()),
        ("concurrency (INFINITO_CI_CONCURRENCY)", setting("INFINITO_CI_CONCURRENCY")),
        ("queue window (INFINITO_CI_QUEUE_HOURS)", setting("INFINITO_CI_QUEUE_HOURS")),
        ("job timeout (minutes)", job_timeout_minutes()),
        ("waves", waves()),
        ("chunk size", chunk_size()),
        ("chunk blocks (INFINITO_CI_MAX_CHUNKS)", setting("INFINITO_CI_MAX_CHUNKS")),
        ("chunks filled", chunk_count()),
        ("rows per sweep", rows_per_sweep()),
    ]
    width = max(len(name) for name, _ in rows)
    lines = [f"{'job':<{width}}  jobs", f"{'-' * width}  ----"]
    lines += [f"{name:<{width}}  {count:>4}" for name, count in breakdown]
    lines.append(f"{'-' * width}  ----")
    lines += [f"{name:<{width}}  {count:>4}" for name, count in rows[len(breakdown) :]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive the deploy-chunk budget of one CI workflow run."
    )
    parser.add_argument("--field", choices=sorted(budget()))
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="Print the per-job budget breakdown as a table.",
    )
    parser.add_argument("--format", choices=("json",), dest="fmt")
    args = parser.parse_args(argv)

    if args.matrix:
        print(render_matrix())
        return 0
    values = budget()
    if args.field:
        print(values[args.field])
        return 0
    print(json.dumps(values) if args.fmt == "json" else json.dumps(values, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
