"""Which test-cluster node holds a backup repository the DR drill can pull.

Single source for the two consumers that must agree: ``extend_inventory``
turns the placements into inventory groups, and ``matrix`` turns the same
placements into ``remote-2-local.backup_providers``. Exception: the group
membership is also what runs ``user-backup`` on that node, so a node named as
a provider without its group has no authorized pull key, and
``roles/svc-bkp-remote-2-local/templates/script.sh.j2`` counts one error per
failing provider and exits 1 for the whole unit.
"""

from __future__ import annotations

from utils.tests.swarm.derive_includes import derive_includes

MANAGER_REPO_ROLES: tuple[str, ...] = (
    "svc-bkp-volume-2-local",
    "svc-bkp-secrets-2-local",
)
NFS_REPO_ROLES: tuple[str, ...] = ("svc-bkp-nfs-2-local",)


def repo_placements(
    *,
    app_closure: list[str],
    nfs_closure: list[str],
    manager: str,
    nfs_server: str,
) -> list[tuple[str, str]]:
    """Pair every backup repository role with the node that will run it.

    Args:
        app_closure: include closure of the round's primary app; induces the
            manager repositories.
        nfs_closure: include closure of svc-storage-nfs-server; induces the
            export-host repository.
        manager: manager node address (inventory host name or IP).
        nfs_server: export node address (inventory host name or IP).

    Returns:
        ``(role_id, node)`` pairs, manager repositories first.
    """
    on_manager = set(app_closure)
    on_nfs = set(nfs_closure)
    return [
        *((role, manager) for role in MANAGER_REPO_ROLES if role in on_manager),
        *((role, nfs_server) for role in NFS_REPO_ROLES if role in on_nfs),
    ]


def backup_provider_ips(
    *,
    app_id: str,
    variants: dict[str, int],
    manager: str,
    nfs_server: str,
) -> list[str]:
    """Nodes the DR drill's remote-2-local unit pulls from.

    Args:
        app_id: primary application of the round.
        variants: the round's ``{app_id: variant_index}`` map.
        manager: manager node IP.
        nfs_server: export node IP.

    Returns:
        provider IPs in placement order, deduplicated.
    """
    placements = repo_placements(
        app_closure=derive_includes(app_id, variants=variants),
        nfs_closure=derive_includes("svc-storage-nfs-server", variants=variants),
        manager=manager,
        nfs_server=nfs_server,
    )
    return list(dict.fromkeys(node for _role, node in placements))
