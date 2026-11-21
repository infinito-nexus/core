"""Does the agents bundle fit its resource budget.

The bundle fits when the warm pool plus ``agents.max_running`` times the
largest runtime memory reservation, plus the infrastructure the bundle always
runs, stays within the repository's per-variant budget. Only ``max_running``
agents run at once and the warm pool holds its VMs started ahead, so the cap is
bounded by the largest single runtime, not the sum of all declared runtimes.

A VM host has to hold the same number of VMs at the largest VM size: its free
memory and storage cover that demand plus a reserve, and the limits of a
hypervisor container cover it plus the hypervisor's own overhead.
"""

from __future__ import annotations

VM_RESOURCES = ("vcpu", "memory", "disk")


def agents_reservation(
    max_running: int, runtime_reservations: dict[str, int], warm_pool: int
) -> int:
    """Return the memory the agents may reserve at once: the warm pool plus
    ``max_running`` times the largest single runtime reservation (0 when none
    run).

    Args:
        max_running: the cap on concurrently running agents.
        runtime_reservations: runtime name to its memory reservation in bytes.
        warm_pool: the VMs kept started ahead of a task.
    """
    count = max_running + warm_pool
    if count <= 0 or not runtime_reservations:
        return 0
    return count * max(runtime_reservations.values())


def fits(
    max_running: int,
    runtime_reservations: dict[str, int],
    infrastructure: int,
    cap: int,
    warm_pool: int,
) -> bool:
    """Return whether the bundle fits: agents reservation plus infrastructure
    within the per-variant ``cap`` (all in bytes).

    Args:
        max_running: the cap on concurrently running agents.
        runtime_reservations: runtime name to its memory reservation in bytes.
        infrastructure: the memory the bundle's own services reserve.
        cap: the per-variant memory budget.
        warm_pool: the VMs kept started ahead of a task.
    """
    reserved = agents_reservation(max_running, runtime_reservations, warm_pool)
    return reserved + infrastructure <= cap


def vm_demand(
    max_running: int, warm_pool: int, sizes: list[dict[str, int]]
) -> dict[str, int]:
    """Return what the VMs of one host need at most: the warm pool plus
    ``max_running`` times the largest VM size, per resource.

    Args:
        max_running: the cap on concurrently running agents.
        warm_pool: the VMs kept started ahead of a task.
        sizes: the VM sizes (vcpu, memory and disk in bytes) of the agents
            this host serves.
    """
    if warm_pool < 0 or max_running < 0:
        raise ValueError(
            f"warm_pool ({warm_pool}) and max_running ({max_running}) must not be negative"
        )
    count = max_running + warm_pool
    return {
        key: count * max((size[key] for size in sizes), default=0)
        for key in VM_RESOURCES
    }


def vm_host_shortages(
    demand: dict[str, int], free: dict[str, int], reserve: dict[str, int]
) -> list[str]:
    """Return one message per resource the host lacks: its free memory and
    storage must cover the demand plus the reserve.

    Args:
        demand: the result of ``vm_demand``.
        free: the host's free ``memory`` and ``disk`` in bytes.
        reserve: the ``memory`` and ``disk`` the host keeps for itself.
    """
    return [
        f"free {key} {free[key]} B is below the {need} B the agent VMs need "
        f"({demand[key]} B for the warm pool and agents.max_running plus a "
        f"{reserve[key]} B reserve)"
        for key in ("memory", "disk")
        for need in (demand[key] + reserve[key],)
        if free[key] < need
    ]


def container_limits(demand: dict[str, int], overhead: dict) -> dict[str, float]:
    """Return the smallest limits a hypervisor container may run with: the VM
    demand plus the hypervisor's own overhead.

    Args:
        demand: the result of ``vm_demand``.
        overhead: the hypervisor's own ``cpus`` and ``memory`` in bytes.
    """
    return {
        "cpus": float(demand["vcpu"]) + float(overhead["cpus"]),
        "memory": demand["memory"] + int(overhead["memory"]),
    }


def container_limit_shortages(
    required: dict[str, float], cpus: float, memory: int
) -> list[str]:
    """Return one message per container limit below the required one.

    Args:
        required: the result of ``container_limits``.
        cpus: the container's CPU limit.
        memory: the container's memory limit in bytes.
    """
    actual = {"cpus": float(cpus), "memory": int(memory)}
    return [
        f"container {key} limit {actual[key]} is below the required "
        f"{required[key]} (warm pool and agents.max_running times the largest "
        "VM size plus the hypervisor overhead)"
        for key in ("cpus", "memory")
        if actual[key] < required[key]
    ]
