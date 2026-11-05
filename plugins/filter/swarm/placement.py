"""Swarm placement constraints of a placement class such as ``manager``."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def swarm_placement_constraints(
    placement, managers: Sequence[str], stack_host_label: str
) -> list[str]:
    """Return the constraints that pin a service to its placement class.

    A manager-placed service of a swarm with more than one manager is also
    pinned to the node carrying the stack-host label.

    Args:
        placement: ``manager``, another node role, or empty for none.
        managers: hosts of ``svc-swarm-manager``.
        stack_host_label: ``SWARM_NODE_LABEL_STACK_HOST``.
    """
    if not placement:
        return []
    constraints = [f"node.role == {placement}"]
    if placement == "manager" and len(managers or []) > 1:
        constraints.append(f"node.labels.{stack_host_label} == true")
    return constraints


class FilterModule:
    def filters(self):
        return {"swarm_placement_constraints": swarm_placement_constraints}
