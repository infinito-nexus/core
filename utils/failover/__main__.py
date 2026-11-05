"""Failover suite CLI.

``python -m utils.failover lab-overrides --out <file>`` writes the lab-size
inventory override, filtered to roles and services that exist.

``python -m utils.failover run --engine <name> --junit <file>`` runs every
scenario that applies to the engine against the Swarm lab named by the
topology environment (``SWARM_LAB_MANAGERS``, ``SWARM_LAB_WORKERS``,
``SWARM_LAB_NETWORK`` and the ``INFINITO_SWARM_*_IP`` addresses exported by
the lab topology script). The cases that redeploy find the lab inventory under
``INFINITO_INVENTORY_DIR``. ``--only`` restricts the run to named scenarios;
``--part`` (default ``$FAILOVER_PART``) to the in-place or the rebuild cases.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.yaml import dump_yaml
from utils.failover.inventory import LabInventory, find_inventory
from utils.failover.junit import CaseResult, write_junit
from utils.failover.procedures import Env
from utils.failover.runner import run_scenario
from utils.failover.scenarios import PARTS, scenarios_for
from utils.failover.swarm import SwarmLab, filter_lab_overrides, load_lab_sizes
from utils.failover.targets import ENGINES, RECLONE_CEILING_S
from utils.tests.swarm.matrix import _DEFAULT_INVENTORY_DIR

_IP_KEYS = {
    "MGR": "INFINITO_SWARM_MGR_IP",
    "MGR2": "INFINITO_SWARM_MGR2_IP",
    "MGR3": "INFINITO_SWARM_MGR3_IP",
    "WRK1": "INFINITO_SWARM_WRK1_IP",
    "WRK2": "INFINITO_SWARM_WRK2_IP",
}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m utils.failover")
    sub = parser.add_subparsers(dest="command", required=True)
    overrides = sub.add_parser("lab-overrides")
    overrides.add_argument("--out", required=True, type=Path)
    run = sub.add_parser("run")
    run.add_argument("--engine", required=True, choices=sorted(ENGINES))
    run.add_argument("--junit", required=True, type=Path)
    run.add_argument("--duration", type=int, default=120)
    run.add_argument("--only", nargs="+", default=None)
    run.add_argument(
        "--part", choices=PARTS, default=os.environ.get("FAILOVER_PART") or None
    )
    return parser.parse_args(argv)


def _lab_inventory() -> LabInventory | None:
    base = os.environ.get("INFINITO_INVENTORY_DIR") or _DEFAULT_INVENTORY_DIR
    try:
        return LabInventory(find_inventory(base))
    except RuntimeError as exc:
        print(f"[WARN] {exc}; the redeploying cases will fail", flush=True)
        return None


def _swarm_lab(engine: str) -> SwarmLab:
    managers = os.environ["SWARM_LAB_MANAGERS"].split()
    workers = os.environ["SWARM_LAB_WORKERS"].split()
    node_ips = {
        os.environ[name]: os.environ[key]
        for name, key in _IP_KEYS.items()
        if os.environ.get(name) and os.environ.get(key)
    }
    return SwarmLab(
        engine=engine,
        managers=managers,
        spare=workers[-1],
        network=os.environ["SWARM_LAB_NETWORK"],
        node_ips=node_ips,
        inventory=_lab_inventory(),
        python=sys.executable,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "lab-overrides":
        dump_yaml(
            str(args.out),
            filter_lab_overrides(load_lab_sizes(), roles_dir=PROJECT_ROOT / "roles"),
        )
        return 0

    lab = _swarm_lab(args.engine)
    env = Env(duration_s=args.duration)
    selected = [
        s
        for s in scenarios_for(args.engine, None if args.only else args.part)
        if not args.only or s.name in args.only
    ]
    cases: list[CaseResult] = []
    for scenario in selected:
        print(f"=== failover {args.engine}: {scenario.name} ===", flush=True)
        try:
            lab.wait_swarm_settled(lab.live_managers())
            ready, detail = lab.wait_ready_for_case(RECLONE_CEILING_S)
            case = (
                run_scenario(
                    lab, args.engine, scenario, duration_s=args.duration, env=env
                )
                if ready
                else CaseResult(
                    name=scenario.name,
                    failures=[f"not at full strength before the case: {detail}"],
                )
            )
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
            case = CaseResult(name=scenario.name, failures=[f"adapter error: {exc}"])
        for line in (*case.failures, *case.notes):
            print(f"    {line}", flush=True)
        cases.append(case)
    write_junit(args.junit, suite=f"failover-{args.engine}", cases=cases)
    return 1 if any(c.failures for c in cases) else 0


if __name__ == "__main__":
    sys.exit(main())
