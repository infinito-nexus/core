from __future__ import annotations

from typing import TYPE_CHECKING

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from cli.administration.inventory.provision.ruamel_io import (
    dump_document,
    ensure_map,
    load_document,
    vault_value,
)
from utils.manager.credential_key import CREDENTIALS_KEY, SECRETS_KEY
from utils.networks.mesh import (
    APPLICATION_ID,
    INTERFACES_KEY,
    interfaces,
    owned_interface,
)

from .keys import is_valid_public_key

if TYPE_CHECKING:
    from pathlib import Path

    from .model import Mesh

HOST_PREFIX_32 = "/32"


PRIVATE_KEY_NAME = "mesh_private_key"


def private_key_name(mesh_name: str | None = None) -> str:
    return PRIVATE_KEY_NAME


def host_vars_path(host_vars_dir: Path, host: str) -> Path:
    return host_vars_dir / f"{host}.yml"


def _interface_list(document: CommentedMap) -> CommentedSeq:
    app = ensure_map(ensure_map(document, "applications"), APPLICATION_ID)
    networks = ensure_map(app, "networks")
    listed = networks.get(INTERFACES_KEY)
    if not isinstance(listed, list):
        listed = CommentedSeq()
        networks[INTERFACES_KEY] = listed
    return listed


def existing_public_keys(
    host_vars_dir: Path, hosts: list[str], mesh_name: str
) -> dict[str, str]:
    found: dict[str, str] = {}
    for host in hosts:
        path = host_vars_path(host_vars_dir, host)
        if not path.exists():
            continue
        document = load_document(path)
        applications = document.get("applications", {})
        own = owned_interface(applications, host, mesh_name)
        owned = [
            entry
            for entry in (own, *interfaces(applications))
            if entry is not None and entry.get("host") == host
        ]
        public_key = next(
            (
                entry["public_key"]
                for entry in owned
                if isinstance(entry.get("public_key"), str)
                and is_valid_public_key(entry["public_key"])
            ),
            None,
        )
        if public_key is None:
            continue
        credentials = (
            applications.get(APPLICATION_ID, {})
            .get(SECRETS_KEY, {})
            .get(CREDENTIALS_KEY, {})
        )
        if private_key_name() not in credentials:
            continue
        found[host] = public_key
    return found


def existing_addresses(
    host_vars_dir: Path, hosts: list[str], mesh_name: str
) -> dict[str, str]:
    found: dict[str, str] = {}
    for host in hosts:
        path = host_vars_path(host_vars_dir, host)
        if not path.exists():
            continue
        entry = owned_interface(
            load_document(path).get("applications", {}), host, mesh_name
        )
        address = (entry or {}).get("address")
        if isinstance(address, str) and address.strip():
            found[host] = address.strip()
    return found


def prune_foreign_meshes(host_vars_dir: Path, hosts: list[str]) -> dict[str, list[str]]:
    removed: dict[str, list[str]] = {}
    for host in hosts:
        path = host_vars_path(host_vars_dir, host)
        if not path.exists():
            continue
        document = load_document(path)
        if not interfaces(document.get("applications", {})):
            continue
        listed = _interface_list(document)
        foreign = [
            entry
            for entry in listed
            if isinstance(entry, dict) and entry.get("host") not in (None, "", host)
        ]
        if not foreign:
            continue
        for entry in foreign:
            listed.remove(entry)
        dump_document(path, document)
        removed[host] = sorted(str(entry.get("name")) for entry in foreign)
    return removed


def _peer_entries(mesh: Mesh, host: str, *, routes_pool: bool) -> list[CommentedMap]:
    entries: list[CommentedMap] = []
    for peer in mesh.peers_of(host):
        entry = CommentedMap()
        entry["host"] = peer.host
        if not peer.roaming:
            entry["endpoint"] = peer.endpoint or peer.host
        entry["public_key"] = peer.public_key
        entry["address"] = peer.address
        if not peer.is_hub:
            entry["allowed_ips"] = peer.address + HOST_PREFIX_32
        elif routes_pool:
            entry["allowed_ips"] = mesh.spec.routed_range or mesh.spec.subnet
        else:
            entry["allowed_ips"] = mesh.spec.subnet
        entry["is_hub"] = peer.is_hub
        entries.append(entry)
    return entries


def _entry_for(listed: CommentedSeq, mesh_name: str) -> CommentedMap:
    for entry in listed:
        if isinstance(entry, dict) and entry.get("name") == mesh_name:
            return entry
    entry = CommentedMap()
    entry["name"] = mesh_name
    listed.append(entry)
    return entry


def write_mesh(
    mesh: Mesh,
    host_vars_dir: Path,
    vault_password_file: Path,
    primary: dict[str, str] | None = None,
    host_vault_password_files: dict[str, Path] | None = None,
) -> list[Path]:
    """Write ``mesh`` into every member's host_vars and return the paths.

    Args:
        mesh: the resolved mesh.
        host_vars_dir: directory holding one ``<host>.yml`` per member.
        vault_password_file: password file the private keys are encrypted with.
        primary: hostname to its primary mesh; an absent host counts this
            mesh as its primary.
        host_vault_password_files: hostname to the password file its own
            private key is encrypted with instead of ``vault_password_file``.
    """
    own_password_files = dict(host_vault_password_files or {})
    written: list[Path] = []
    key_name = private_key_name()

    for member in mesh.members:
        path = host_vars_path(host_vars_dir, member.host)
        document = load_document(path) if path.exists() else CommentedMap()
        is_primary = (primary or {}).get(member.host, mesh.spec.name) == mesh.spec.name

        entry = _entry_for(_interface_list(document), mesh.spec.name)
        app = document["applications"][APPLICATION_ID]
        entry["host"] = member.host
        entry["address"] = member.address
        entry["subnet"] = mesh.spec.subnet
        entry["listen_port"] = mesh.spec.listen_port
        entry["is_hub"] = member.is_hub
        entry["primary"] = is_primary
        entry["public_key"] = member.public_key
        entry["peers"] = _peer_entries(mesh, member.host, routes_pool=is_primary)

        if member.private_key is not None:
            credentials = ensure_map(ensure_map(app, SECRETS_KEY), CREDENTIALS_KEY)
            credentials[key_name] = vault_value(
                own_password_files.get(member.host, vault_password_file),
                member.private_key,
                key_name,
            )

        dump_document(path, document)
        written.append(path)
    return written
