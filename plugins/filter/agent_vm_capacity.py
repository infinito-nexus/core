from __future__ import annotations

from utils.agents import budget, vm_template, workspace
from utils.sizes import docker_to_bytes, to_bytes


def _free_disk(mounts: list[dict], path: str) -> int:
    best = None
    for mount in mounts or []:
        point = str(mount.get("mount", ""))
        inside = path == point or path.startswith(point.rstrip("/") + "/")
        if inside and (best is None or len(point) > len(str(best["mount"]))):
            best = mount
    return int(best["size_available"]) if best else 0


def _on_host(raw: object, kind: str, host: str) -> bool:
    return (
        isinstance(raw, dict) and raw.get("kind") == kind and raw.get("target") == host
    )


def agent_vm_problems(
    agents: dict[str, dict], kind: str, host: str, inventory_hosts: list[str]
) -> list[str]:
    """Return every workspace contract break of the merged agent configs whose
    workspace runs on ``host``, as ``<role>: <problem>``.

    Args:
        agents: role name to its merged agent configuration, inventory included.
        kind: the VM kind the host serves.
        host: the inventory host name of the hypervisor.
        inventory_hosts: every host name of the inventory.
    """
    runtimes = vm_template.runtimes(vm_template.TEMPLATE_DIR)
    return [
        f"{role}: {problem}"
        for role, agent in sorted((agents or {}).items())
        if _on_host(agent.get("workspace"), kind, host)
        for problem in workspace.problems(agent, frozenset(inventory_hosts), runtimes)
    ]


def agent_vm_stray_targets(
    agents: dict[str, dict], hypervisors: dict[str, list[str]]
) -> list[str]:
    """Return every agent with a VM workspace whose ``target`` is no host of
    its kind's hypervisor role, as ``<role>: <problem>``; no hypervisor host
    checks or warns about such an agent, so this check runs once per play.

    Args:
        agents: role name to its merged agent configuration, inventory included.
        hypervisors: VM kind to the inventory hosts that run its hypervisor role.
    """
    return [
        f"{role}: workspace.kind {raw['kind']} targets '{raw.get('target')}', "
        f"which runs no {raw['kind']} hypervisor"
        for role, agent in sorted((agents or {}).items())
        if isinstance(raw := agent.get("workspace"), dict)
        and raw.get("kind") in workspace.VM_KINDS
        and raw.get("target") not in (hypervisors.get(raw["kind"]) or [])
    ]


def agent_vm_sizes(workspaces: list[dict], kind: str, host: str) -> list[dict]:
    """Return the VM sizes of the agents whose workspace runs on ``host``.

    Args:
        workspaces: the merged ``workspace`` mapping of every agent role.
        kind: the VM kind the host serves.
        host: the inventory host name of the hypervisor.
    """
    return [
        workspace.vm_size(raw.get("resources"))
        for raw in workspaces or []
        if _on_host(raw, kind, host)
    ]


def agent_login_notice(workspaces: list[dict], kind: str, host: str) -> str:
    """Return the login-mode warning for the VM workspaces on ``host``, or "".

    Args:
        workspaces: the merged ``workspace`` mapping of every agent role.
        kind: the VM kind the host serves.
        host: the inventory host name of the hypervisor.
    """
    count = sum(
        1
        for raw in workspaces or []
        if _on_host(raw, kind, host) and raw.get("model_access") == "login"
    )
    if not count:
        return ""
    return (
        f"{count} agent VM workspace(s) on {host} use model_access login: "
        "LiteLLM's model list, quotas and spend log do not apply to them, and "
        "each vendor login token stays valid at the vendor until the operator "
        "revokes it there."
    )


def agent_vm_capacity(
    workspaces: list[dict],
    kind: str,
    host: str,
    max_running: int,
    warm_pool: int,
    reserve: dict,
    free_memory: int,
    running_memory: int,
    mounts: list[dict],
    storage_path: str,
    pool_size: str,
    pool_used: int,
    own_disk: int,
    overhead: dict,
    limits: dict,
) -> list[str]:
    """Return every capacity shortage of a VM host: free memory and storage
    below the VM demand plus the reserve, a fixed storage pool below the VM
    demand, and, when ``limits`` is non-empty, container limits below the VM
    demand plus the hypervisor overhead.

    Args:
        workspaces: the merged ``workspace`` mapping of every agent role.
        kind: the VM kind the host serves.
        host: the inventory host name of the hypervisor.
        max_running: ``agents.max_running`` of the broker.
        warm_pool: the VMs the host keeps started ahead.
        reserve: ``memory`` and ``disk`` sizes the host keeps for itself.
        free_memory: the host's free memory in bytes.
        running_memory: memory in bytes the role's own running VMs hold now;
            a redeploy gets it back, so it counts as free.
        mounts: ``ansible_facts.mounts``.
        storage_path: the path the VM disks live under.
        pool_size: the fixed size of the storage pool the VM disks live in,
            which must hold the demand alone, as the reserve stays with
            ``storage_path``; "" when the disks take the free space of
            ``storage_path``.
        pool_used: bytes the pool already holds; 0 without a fixed pool.
        own_disk: bytes the role's own VM disks take, part of ``pool_used``
            and of the used space of ``storage_path``; a redeploy gets them
            back, so they count as free in both.
        overhead: the hypervisor's own ``cpus`` and ``memory`` size.
        limits: the container's ``cpus`` and ``mem_limit``; empty on a bare host.
    """
    demand = budget.vm_demand(
        int(max_running), int(warm_pool), agent_vm_sizes(workspaces, kind, host)
    )
    found = budget.vm_host_shortages(
        demand,
        {
            "memory": int(free_memory) + int(running_memory),
            "disk": _free_disk(mounts, storage_path) + int(own_disk),
        },
        {"memory": to_bytes(reserve["memory"]), "disk": to_bytes(reserve["disk"])},
    )
    pool = to_bytes(pool_size) - int(pool_used) + int(own_disk) if pool_size else None
    if pool is not None and pool < demand["disk"]:
        found.append(
            f"free disk {pool} B of the fixed storage pool is below the "
            f"{demand['disk']} B the warm pool and agents.max_running need; "
            "the reserve stays outside the pool"
        )
    if limits:
        required = budget.container_limits(
            demand,
            {"cpus": overhead["cpus"], "memory": to_bytes(overhead["memory"])},
        )
        found.extend(
            budget.container_limit_shortages(
                required, float(limits["cpus"]), docker_to_bytes(limits["mem_limit"])
            )
        )
    return found


class FilterModule:
    def filters(self):
        return {
            "agent_login_notice": agent_login_notice,
            "agent_vm_capacity": agent_vm_capacity,
            "agent_vm_problems": agent_vm_problems,
            "agent_vm_stray_targets": agent_vm_stray_targets,
        }
