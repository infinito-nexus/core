"""Filters for removing the Tor tree earlier deploys kept under DIR_VAR_LIB.

Usage:

    {{ query('node_hosts') | tor_legacy_nodes(swarm_nodes, nfs_clients, STACK_HOST) }}
    {{ _resolved | tor_legacy_removable(_legacy_stat, _live_stat) }}
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def tor_legacy_nodes(
    nodes: list[str], swarm: list[str], clients: list[str], stack_host: str
) -> list[str]:
    """Hosts that remove the legacy tree, each tree exactly once.

    Args:
        nodes: every node that holds Tor state (``query('node_hosts')``).
        swarm: the ``svc-swarm-node`` group.
        clients: the ``svc-storage-nfs-client`` group.
        stack_host: the stack host.

    Returns:
        One host that mounts the NFS-shared DIR_VAR_LIB (the stack host when it
        does, else the first mounting swarm node), then every node whose
        DIR_VAR_LIB is local. A host mounts it when it is in both groups, the
        predicate tasks/stages/02_server.yml includes svc-storage-nfs-client by.
        Kept in Python because Ansible's ``intersect`` returns set order.
    """
    mounters = [node for node in swarm if node in clients]
    shared = [stack_host] if stack_host in mounters else mounters[:1]
    return shared + [node for node in nodes if node not in mounters]


def tor_legacy_removable(
    resolved: list[str], legacy: dict[str, Any], live: dict[str, Any]
) -> bool:
    """Whether removing the legacy tree leaves the live Tor state untouched.

    Args:
        resolved: ``realpath -m`` of the legacy tree and of the live data
            directory, in that order.
        legacy: ``stat`` of the legacy tree.
        live: ``stat`` of the live data directory's parent.

    Returns:
        True only when the legacy tree is a directory that is neither the live
        parent (same device and inode, as a bind mount or symlink makes it) nor
        an ancestor of the live data directory once symlinks are resolved.
    """
    if not (legacy.get("exists") and legacy.get("isdir")):
        return False
    if live.get("exists") and (legacy["dev"], legacy["inode"]) == (
        live["dev"],
        live["inode"],
    ):
        return False
    legacy_real, live_real = resolved
    return not PurePosixPath(live_real).is_relative_to(legacy_real)


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {
            "tor_legacy_nodes": tor_legacy_nodes,
            "tor_legacy_removable": tor_legacy_removable,
        }
