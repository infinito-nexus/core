"""Derive the deploy-matrix job slots per mode from the CI workflow chain.

Usage:
  python -m cli.meta.ci.slots [--mode compose|swarm|host] [--matrix] [--format json]

GitHub caps a workflow run's job matrix at 256 jobs
(INFINITO_CI_JOB_LIMIT). Every non-deploy job the orchestrator chain
spawns in the same run eats into that budget, so this module statically
and CONSERVATIVELY counts them:

* every orchestrator job reserves its full job count -- reusable
  workflows are opened and summed, static matrices multiplied out,
  dynamic (``fromJson``) matrices estimated at
  ``_DYNAMIC_MATRIX_ESTIMATE``;
* the deploy callers themselves reserve only their static jobs (the
  discover steps); their dynamic per-app matrices are exactly the slots
  being budgeted.

The worst entry point (``entry-*.yml``) adds its own jobs to the same
run before calling the orchestrator; that overhead is subtracted too.

The remaining slots are split between the deploy matrices by the
``_SHARES`` weights (compose bundles variants and turns over fastest;
swarm jobs are the heaviest; host roles are few), with a floor of
``_MIN_MODE_SLOTS`` per mode because tiny budgets make the complexity
report emit an empty matrix. ``_SLOT_OVERRIDES`` pins a mode to a fixed
value and wins over every derived number.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import TYPE_CHECKING

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

if TYPE_CHECKING:
    from pathlib import Path

_SHARES = {"compose": 7, "swarm": 9, "host": 1}

_SLOT_OVERRIDES: dict[str, int] = {}

_DEPLOY_CALLERS = frozenset(
    {
        "test-deploy-single-node",
        "test-deploy-single-node-priority",
        "test-deploy-swarm",
        "test-deploy-swarm-priority",
    }
)

_ORCHESTRATOR = ".github/workflows/ci-orchestrator.yml"
_DYNAMIC_MATRIX_ESTIMATE = 5
_DEFAULT_JOB_LIMIT = 256
_MIN_MODE_SLOTS = 3


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


def reserved_breakdown(repo_root: Path | None = None) -> list[tuple[str, int]]:
    """Per orchestrator job: the job count it reserves in the run budget.
    Deploy callers contribute only their static jobs (the discover steps);
    their dynamic per-app matrices are the budgeted slots themselves."""
    root = repo_root or PROJECT_ROOT
    jobs = _jobs(_load_workflow(root / _ORCHESTRATOR))
    return [
        (name, _job_slots(root, job, count_dynamic=name not in _DEPLOY_CALLERS))
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


def mode_slots(repo_root: Path | None = None) -> dict[str, int]:
    """Deploy slots per mode: (run job limit - reserved - worst entry
    overhead) split by _SHARES, then pinned values from _SLOT_OVERRIDES."""
    limit = int(os.environ.get("INFINITO_CI_JOB_LIMIT") or _DEFAULT_JOB_LIMIT)
    available = max(
        limit - reserved_slots(repo_root) - entry_overhead(repo_root), len(_SHARES)
    )
    total_shares = sum(_SHARES.values())
    slots = {
        mode: max(available * share // total_shares, _MIN_MODE_SLOTS)
        for mode, share in _SHARES.items()
    }
    slots.update(_SLOT_OVERRIDES)
    return slots


def render_matrix() -> str:
    """The budget as a CLI table: per-job reservations, then the totals
    and the per-mode share split."""
    breakdown = reserved_breakdown()
    reserved = sum(count for _, count in breakdown)
    overhead = entry_overhead()
    limit = int(os.environ.get("INFINITO_CI_JOB_LIMIT") or _DEFAULT_JOB_LIMIT)
    slots = mode_slots()
    width = max(
        len(name)
        for name, _ in [
            *breakdown,
            ("job limit (INFINITO_CI_JOB_LIMIT)", 0),
            ("entry overhead (worst entry-*.yml)", 0),
        ]
    )
    lines = [f"{'job':<{width}}  jobs", f"{'-' * width}  ----"]
    lines += [f"{name:<{width}}  {count:>4}" for name, count in breakdown]
    lines += [
        f"{'-' * width}  ----",
        f"{'reserved':<{width}}  {reserved:>4}",
        f"{'entry overhead (worst entry-*.yml)':<{width}}  {overhead:>4}",
        f"{'job limit (INFINITO_CI_JOB_LIMIT)':<{width}}  {limit:>4}",
        f"{'available':<{width}}  {max(limit - reserved - overhead, len(_SHARES)):>4}",
        f"{'-' * width}  ----",
    ]
    lines += [
        f"{_mode_label(mode):<{width}}  {slots[mode]:>4}" for mode in sorted(_SHARES)
    ]
    return "\n".join(lines)


def _mode_label(mode: str) -> str:
    if mode in _SLOT_OVERRIDES:
        return f"{mode} (override)"
    return f"{mode} (share {_SHARES[mode]})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive deploy-matrix job slots per mode from the CI chain."
    )
    parser.add_argument("--mode", choices=sorted(_SHARES))
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
    slots = mode_slots()
    if args.mode:
        print(slots[args.mode])
        return 0
    print(
        json.dumps(
            {"reserved": reserved_slots(), "entry_overhead": entry_overhead(), **slots}
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
