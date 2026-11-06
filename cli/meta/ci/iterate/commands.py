"""The make command each planned row runs.

The compose redeploy a diff needs comes from :mod:`utils.roles.redeploy`. The
compose iteration routine keeps its own copy of that rule until the merge
switches it to the same module; the unit tests pin both to one answer.
"""

from __future__ import annotations

from utils.roles.redeploy import REINSTALL, ROLE_SYNC, UPDATE, spec_only
from utils.roles.redeploy import compose_redeploy as redeploy

__all__ = ("REINSTALL", "ROLE_SYNC", "UPDATE", "command", "redeploy", "spec_only")

GATE = "gate"
PLAYWRIGHT = "playwright"
ZOMBIE = "zombie"
ROUNDTRIP = "roundtrip"
ACT = "act"


def _args(**values: str) -> str:
    return " ".join(f"{key}={value}" for key, value in values.items() if value)


def command(
    deploy: str,
    app: str,
    *,
    variant: int,
    variants: int,
    disable: str,
    network: str,
) -> str:
    """Return the make command of one row.

    Args:
        deploy: the row's deploy kind (a constant of this module).
        app: the application id.
        variant: the variant index the row pins.
        variants: how many variants the role declares; a single-variant role
            takes no ``variant=`` in compose, whose reuse path would otherwise
            look for a round folder that only matrix roles have.
        disable: comma-separated provider keys to render disabled.
        network: the node network mode a swarm row pins.
    """
    pin = str(variant) if variants > 1 else ""
    if deploy == ROLE_SYNC:
        return f"make compose-role-sync {_args(role=app, variant=pin)}"
    if deploy == PLAYWRIGHT:
        return f"make compose-playwright {_args(role=app)}"
    if deploy == UPDATE:
        args = _args(mode="update", apps=app, variant=pin, disable=disable)
        return f"make compose-deploy {args}"
    if deploy == REINSTALL:
        args = _args(
            mode="reinstall", apps=app, full_cycle="true", variant=pin, disable=disable
        )
        return f"make compose-deploy {args}"
    if deploy == GATE:
        args = _args(mode="reinstall", apps=app, full_cycle="true", disable=disable)
        return f"make compose-deploy {args}"
    if deploy == ZOMBIE:
        args = _args(app=app, variant=str(variant), network=network, disable=disable)
        return f"make swarm-zombie {args}"
    if deploy == ROUNDTRIP:
        return f"make roundtrip {_args(disable=disable)}".strip()
    if deploy == ACT:
        return "make act-workflow"
    raise ValueError(f"unknown deploy kind {deploy!r}")
