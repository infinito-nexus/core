"""Role sync against the kept swarm-test cluster, run inside its act job container."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from utils import PROJECT_ROOT
from utils.tests.swarm import deploy
from utils.tests.swarm.matrix import DEPLOY_EXTRAS_FILE

_ROLES_DIR = str(PROJECT_ROOT / "roles")
_APP_ID = re.compile(r"[a-z0-9][a-z0-9-]*")


def round_inventory(*, app_id: str, variant: int, base_dir: str) -> Path:
    """Return the inventory directory the matrix wrote for one round.

    Args:
        app_id: primary application of the run.
        variant: variant index of the round.
        base_dir: base inventory directory the matrix derived its rounds from.

    Returns:
        The round's inventory directory, named as the matrix planner names it.
    """
    from cli.administration.deploy.development.inventory import (
        plan_dev_inventory_matrix,
    )

    plan = plan_dev_inventory_matrix(
        roles_dir=_ROLES_DIR, primary_apps=[app_id], base_inventory_dir=base_dir
    )
    for round_index, inv_dir, *_ in plan:
        if round_index == variant:
            return Path(inv_dir.rstrip("/"))
    raise SystemExit(
        f"swarm-role-sync: {app_id} has no variant {variant} ({len(plan)} round(s))"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="utils.tests.swarm.sync",
        description="Run the role of one application again on the kept cluster.",
    )
    parser.add_argument("--app", required=True, help="Application id.")
    parser.add_argument(
        "--variant", type=int, required=True, help="Variant index of the round."
    )
    args = parser.parse_args(argv)
    if not _APP_ID.fullmatch(args.app):
        raise SystemExit(f"swarm-role-sync: not an application id: {args.app!r}")

    inv_dir = round_inventory(
        app_id=args.app,
        variant=args.variant,
        base_dir=os.environ["INFINITO_INVENTORY_DIR"],
    )
    if not (inv_dir / "devices.yml").is_file():
        raise SystemExit(
            f"swarm-role-sync: no round inventory at {inv_dir}/devices.yml; this "
            "act job container holds only the rounds its own swarm-zombie run wrote"
        )
    return deploy.sync_role(
        app_id=args.app,
        inv_dir=str(inv_dir),
        extras_path=str(inv_dir / DEPLOY_EXTRAS_FILE),
        round_index=args.variant,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
