"""Rank the matrix rows that can host a provider which has no row of its own.

Usage:
  python -m cli.meta.ci.host_rows --provides <service key> --mode swarm
      [--limit N] [--format json]

A host-mode-only provider such as svc-bkp-volume-2-local never gets a swarm
row, so a swarm iteration on it deploys it inside another row's closure. Every
row whose include set carries the provider qualifies, but those sets differ by
more than an order of magnitude in what they pull. The rows are ranked by the
summed ``min_storage`` of the include set the provision step derives, then by
the complexity ``weight``, then by token, so the lightest host comes first.

The storage sum is a heuristic: min_storage mixes image bytes with data
reservations, and the include set leaves out the roles extend_inventory adds
per host. It still separates the light rows from the heavy ones, which the
static complexity closure cannot: that one counts every ``in group_names`` gate
as on, and those gates reach the AI stack from almost every role, which ranks
nearly every row as heavy.
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
from typing import TYPE_CHECKING, NamedTuple

from humanfriendly import format_size

from cli.administration.deploy.development.inventory.planner import (
    plan_dev_inventory_matrix,
)
from cli.meta.roles.applications.complexity.model import (
    compute_variant_complexity_rows,
)
from utils.cache.files import PROJECT_ROOT
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.storage.constrained import StorageDeclarationError, closure_storage
from utils.tests.swarm.derive_includes import derive_includes

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from cli.meta.roles.applications.complexity.model import ComplexityRow

ROLES_DIR = PROJECT_ROOT / "roles"


class Closure(NamedTuple):
    """The include set of one round.

    Attributes:
        roles: every role the provision step includes, the primary app too.
        variants: the round's per-app variant index.
    """

    roles: tuple[str, ...]
    variants: dict[str, int]


class HostRow(NamedTuple):
    """One row whose include set carries the provider.

    Attributes:
        app: the row's primary application.
        variant: its variant index.
        roles: the include set.
        storage_bytes: the min_storage the include set declares in total.
        weight: the row's complexity weight.
    """

    app: str
    variant: int
    roles: tuple[str, ...]
    storage_bytes: int
    weight: int

    @property
    def token(self) -> str:
        return f"{self.app}#{self.variant}"


def swarm_closure(app: str, variant: int) -> Closure:
    """Return the include set the provision step derives for a swarm round of app#variant.

    It is the set utils.tests.swarm.matrix hands the provision step, so a
    ``disable`` in the environment prunes it the same way. The roles
    extend_inventory adds per host and a disable list of the CI matrix row are
    not part of it.

    Raises:
        SystemExit: the app declares no such variant.
    """
    variants = round_variants(app, variant)
    return Closure(tuple(derive_includes(app, variants=variants)), variants)


def round_variants(app: str, variant: int) -> dict[str, int]:
    """
    Args:
        app: the row's application id.
        variant: the row's variant index, the round index of its deploy.

    Returns:
        The variant every role runs in that round, the map the dev deploy
        plans for it and hands its storage sum.

    Raises:
        SystemExit: the app declares no such variant.
    """
    plan = _plan(str(ROLES_DIR), app)
    if not 0 <= variant < len(plan):
        raise SystemExit(f"{app}#{variant}: the role declares {len(plan)} variant(s)")
    return dict(plan[variant])


@functools.cache
def _plan(roles_dir: str, app: str) -> tuple[dict[str, int], ...]:
    return tuple(
        entry[2]
        for entry in plan_dev_inventory_matrix(
            roles_dir=roles_dir, primary_apps=[app], base_inventory_dir="plan"
        )
    )


CLOSURES: dict[str, Callable[[str, int], Closure]] = {"swarm": swarm_closure}


def provider_role(provides: str) -> str:
    """Return the role registered for a service key.

    Raises:
        SystemExit: no role provides the key.
    """
    entry = build_service_registry_from_roles_dir(ROLES_DIR).get(provides) or {}
    role = entry.get("role")
    if not role:
        raise SystemExit(f"no role provides the service key {provides!r}")
    return role


def rank(
    rows: Iterable[ComplexityRow],
    *,
    provider: str,
    mode: str,
    closure: Callable[[str, int], Closure],
    footprint: Callable[[Iterable[str], dict[str, int]], dict[str, int]],
) -> list[HostRow]:
    """Return the rows whose include set carries provider, lightest first.

    Args:
        rows: per-variant complexity rows; only those CI tests in mode count.
        provider: the role a host row has to deploy.
        mode: the deploy mode the host row runs in.
        closure: resolves a row's include set from its app and variant.
        footprint: the declared bytes per role of an include set.
    """
    hosts: list[HostRow] = []
    for row in rows:
        if not getattr(row, f"test_{mode}"):
            continue
        resolved = closure(row.name, row.variant)
        if provider not in resolved.roles:
            continue
        declared = footprint(resolved.roles, resolved.variants)
        hosts.append(
            HostRow(
                row.name,
                row.variant,
                resolved.roles,
                sum(declared.values()),
                row.weight,
            )
        )
    return sorted(hosts, key=lambda h: (h.storage_bytes, h.weight, h.app, h.variant))


def render(hosts: list[HostRow]) -> str:
    """Return the ranking as one line per row, rank first."""
    return "\n".join(
        f"{index:>3}  {host.token:<40} {format_size(host.storage_bytes, binary=True):>10}"
        f"  {len(host.roles):>3} roles  weight {host.weight}"
        for index, host in enumerate(hosts, start=1)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rank the rows that can host a provider without a row of its own, "
            "lightest declared include set first."
        )
    )
    parser.add_argument(
        "--provides",
        required=True,
        metavar="SERVICE_KEY",
        help="service key of the provider, e.g. container_backup",
    )
    parser.add_argument("--mode", required=True, choices=sorted(CLOSURES))
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="rows to print; 0 prints every host row (default: 10)",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    try:
        hosts = rank(
            compute_variant_complexity_rows(ROLES_DIR),
            provider=provider_role(args.provides),
            mode=args.mode,
            closure=CLOSURES[args.mode],
            footprint=closure_storage(ROLES_DIR),
        )
    except StorageDeclarationError as exc:
        raise SystemExit(f"host rows: {exc}") from exc
    shown = hosts[: args.limit] if args.limit else hosts
    if args.format == "json":
        print(
            json.dumps(
                [
                    {**host._asdict(), "roles": list(host.roles), "token": host.token}
                    for host in shown
                ]
            )
        )
    else:
        print(render(shown))
    return 0


if __name__ == "__main__":
    sys.exit(main())
