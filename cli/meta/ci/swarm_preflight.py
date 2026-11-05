"""Refuse a swarm round whose declared storage cannot fit the free disk.

Usage:
  python -m cli.meta.ci.swarm_preflight --app <application id> --variant <index>

The in-run watchdog (utils/tests/swarm/watchdog.py) ends the deploy step once
free space drops under DISK_FLOOR_MB, which on a closure that never fit costs
the cluster bring-up plus every role deployed before the cut. This check runs
before act starts: it prints the include set the provision step derives for the
round (pruned by a ``disable`` in the environment, as the provision step prunes
it) with the min_storage each role declares, and refuses when the declared
total plus the watchdog floor exceeds the free space. Free space is the lowest
of Docker's data root and the roots the watchdog samples, so the check never
passes where the watchdog would trip at once.

The total is a heuristic, not a measurement. The include set leaves out the
roles extend_inventory adds per host (svc-swarm-node, the NFS server, WireGuard,
the backup host) and does not see a disable list the CI matrix row adds on its
own. The declared sum is also deliberately not multiplied by the swarm node
count: min_storage mixes image bytes, which every node that runs a task pulls,
with data reservations, which land once on the NFS export or never fill, so no
single factor fits every role, and a per-node factor would refuse every row
that carries a large reservation such as the mail server's. A measured
web-app-wordpress#0 run consumed more than its deployed roles declared, which is
why the in-run watchdog stays the guard beyond this check.
"""

from __future__ import annotations

import argparse
import sys

from humanfriendly import format_size

from cli.meta.ci.host_rows import ROLES_DIR, swarm_closure
from utils.storage.constrained import (
    StorageDeclarationError,
    closure_storage,
    is_constrained,
    resolved_docker_root_free_bytes,
)
from utils.tests.swarm.watchdog import DISK_FLOOR_MB, STORAGE_ROOTS, lowest_free_mb

FLOOR_BYTES = DISK_FLOOR_MB * 2**20
BYPASS = "pass preflight=false to skip this check"


def fits(*, declared_bytes: int, free_bytes: int) -> bool:
    """Return True when the declared closure plus the watchdog floor fits.

    Args:
        declared_bytes: the min_storage the closure declares in total.
        free_bytes: free space, as free_space measures it.
    """
    return not is_constrained(
        free_bytes=free_bytes, required_bytes=declared_bytes + FLOOR_BYTES
    )


def free_space() -> int:
    """Return the lowest free space of Docker's data root and the watchdog roots.

    Raises:
        RuntimeError: as resolved_docker_root_free_bytes.
    """
    return min(resolved_docker_root_free_bytes(), lowest_free_mb()[0] * 2**20)


def _size(value: int) -> str:
    return format_size(value, binary=True)


def report(token: str, declared: dict[str, int], *, free_bytes: int) -> list[str]:
    """Return the totals line, then every declaring role, heaviest first.

    Args:
        token: the row, as app#variant.
        declared: the closure's roles mapped to their declared bytes.
        free_bytes: free space, as free_space measures it.
    """
    heaviest = sorted(declared.items(), key=lambda item: (-item[1], item[0]))
    header = (
        f"=== swarm pre-flight {token}: {len(declared)} roles declare "
        f"{_size(sum(declared.values()))} + {_size(FLOOR_BYTES)} watchdog floor, "
        f"{_size(free_bytes)} free on the fullest of Docker's data root and "
        f"{', '.join(STORAGE_ROOTS)} ==="
    )
    return [
        header,
        *(f"  {_size(size):>10}  {role}" for role, size in heaviest if size),
    ]


def refusal(token: str) -> str:
    """Return the message that ends a run whose closure does not fit."""
    return (
        f"REFUSED: {token} does not fit the free disk. Drop the providers the "
        "role under test does not consume with disable=<keys> (the heaviest are "
        "listed above), pick a lighter host row with `python -m "
        "cli.meta.ci.host_rows --provides <service key> --mode swarm`, free disk "
        f"space, or {BYPASS}."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refuse a swarm round whose declared storage plus the watchdog floor "
            "exceeds the free disk."
        )
    )
    parser.add_argument("--app", required=True, help="the row's application id")
    parser.add_argument(
        "--variant", required=True, type=int, help="the row's variant index"
    )
    args = parser.parse_args(argv)

    token = f"{args.app}#{args.variant}"
    closure = swarm_closure(args.app, args.variant)
    try:
        declared = closure_storage(ROLES_DIR)(closure.roles, closure.variants)
        free_bytes = free_space()
    except (RuntimeError, StorageDeclarationError) as exc:
        raise SystemExit(f"swarm pre-flight {token}: {exc}; {BYPASS}") from exc
    print("\n".join(report(token, declared, free_bytes=free_bytes)), flush=True)
    if fits(declared_bytes=sum(declared.values()), free_bytes=free_bytes):
        return 0
    print(refusal(token), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
