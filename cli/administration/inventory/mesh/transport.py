"""Move an inventory's Ansible transport onto the mesh it just created.

The first pass of a deploy reaches the hosts however it can -- an underlay
address, a container connection -- because no tunnel exists yet and the pass
is what creates one. Every pass after it connects over the mesh, which is what
makes the mesh load-bearing rather than merely present: if it is broken, the
deploy cannot reach a single host, and no role can quietly fall back to the
underlay it was supposed to stop using.

The rewrite is a separate step rather than a fact set during the play, because
a play cannot change the transport it is already running over.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cli.administration.inventory.provision.ruamel_io import (
    dump_document,
    load_document,
)

from .write import DEFAULT_APPLICATION_ID, MESHES_KEY, host_vars_path

if TYPE_CHECKING:
    from pathlib import Path

SSH_CONNECTION = "ssh"


def mesh_address(
    host_vars_dir: Path,
    host: str,
    mesh_name: str,
    application_id: str = DEFAULT_APPLICATION_ID,
) -> str | None:
    """The address *host* holds on *mesh_name*, or ``None`` when it is absent."""
    path = host_vars_path(host_vars_dir, host)
    if not path.exists():
        return None
    entry = (
        load_document(path)
        .get("applications", {})
        .get(application_id, {})
        .get(MESHES_KEY, {})
        .get(mesh_name, {})
    )
    if entry.get("host") != host:
        return None
    address = entry.get("address")
    return address if isinstance(address, str) and address else None


def switch_to_mesh(
    host_vars_dir: Path,
    hosts: list[str],
    mesh_name: str,
    *,
    user: str,
    private_key_file: str,
    application_id: str = DEFAULT_APPLICATION_ID,
) -> dict[str, str]:
    """Point every member of *mesh_name* at its mesh address over SSH.

    Returns:
        Host to the address it was switched to. A host with no address on this
        mesh is left alone -- it is not a member, and rewriting it would
        strand a host that was reachable.
    """
    switched: dict[str, str] = {}
    for host in hosts:
        address = mesh_address(host_vars_dir, host, mesh_name, application_id)
        if address is None:
            continue
        path = host_vars_path(host_vars_dir, host)
        document = load_document(path)
        document["ansible_host"] = address
        document["ansible_connection"] = SSH_CONNECTION
        document["ansible_user"] = user
        document["ansible_ssh_private_key_file"] = private_key_file
        dump_document(path, document)
        switched[host] = address
    return switched
