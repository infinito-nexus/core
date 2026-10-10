"""Project a resolved mesh onto the host_vars of every member."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ruamel.yaml.comments import CommentedMap

from cli.administration.inventory.provision.ruamel_io import (
    dump_document,
    ensure_map,
    load_document,
    vault_value,
)
from utils.manager.credential_key import CREDENTIALS_KEY, SECRETS_KEY

from .keys import is_valid_public_key

if TYPE_CHECKING:
    from pathlib import Path

    from .model import Mesh

DEFAULT_APPLICATION_ID = "svc-net-wireguard"
MESHES_KEY = "meshes"
HOST_PREFIX_32 = "/32"


PRIVATE_KEY_NAME = "mesh_private_key"


def private_key_name(mesh_name: str | None = None) -> str:
    """The credential key a member's own secret half is stored under."""
    return PRIVATE_KEY_NAME


def host_vars_path(host_vars_dir: Path, host: str) -> Path:
    return host_vars_dir / f"{host}.yml"


def _mesh_entry(document: CommentedMap, mesh_name: str, application_id: str) -> dict:
    return (
        document.get("applications", {})
        .get(application_id, {})
        .get(MESHES_KEY, {})
        .get(mesh_name, {})
    )


def existing_public_keys(
    host_vars_dir: Path,
    hosts: list[str],
    mesh_name: str,
    application_id: str = DEFAULT_APPLICATION_ID,
) -> dict[str, str]:
    """The public keys already issued to ``hosts`` for ``mesh_name``."""
    found: dict[str, str] = {}
    for host in hosts:
        path = host_vars_path(host_vars_dir, host)
        if not path.exists():
            continue
        document = load_document(path)
        meshes = (
            document.get("applications", {}).get(application_id, {}).get(MESHES_KEY, {})
        )
        owned = [
            entry
            for entry in (
                _mesh_entry(document, mesh_name, application_id),
                *meshes.values(),
            )
            if isinstance(entry, dict) and entry.get("host") == host
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
            document.get("applications", {})
            .get(application_id, {})
            .get(SECRETS_KEY, {})
            .get(CREDENTIALS_KEY, {})
        )
        if private_key_name() not in credentials:
            continue
        found[host] = public_key
    return found


def existing_addresses(
    host_vars_dir: Path,
    hosts: list[str],
    mesh_name: str,
    application_id: str = DEFAULT_APPLICATION_ID,
) -> dict[str, str]:
    """The addresses already issued to ``hosts`` on ``mesh_name``."""
    found: dict[str, str] = {}
    for host in hosts:
        path = host_vars_path(host_vars_dir, host)
        if not path.exists():
            continue
        entry = _mesh_entry(load_document(path), mesh_name, application_id)
        if not isinstance(entry, dict) or entry.get("host") != host:
            continue
        address = entry.get("address")
        if isinstance(address, str) and address.strip():
            found[host] = address.strip()
    return found


def prune_foreign_meshes(
    host_vars_dir: Path,
    hosts: list[str],
    application_id: str = DEFAULT_APPLICATION_ID,
) -> dict[str, list[str]]:
    """Drop mesh entries a host does not own, returning what was removed."""
    removed: dict[str, list[str]] = {}
    for host in hosts:
        path = host_vars_path(host_vars_dir, host)
        if not path.exists():
            continue
        document = load_document(path)
        meshes = (
            document.get("applications", {}).get(application_id, {}).get(MESHES_KEY, {})
        )
        foreign = [
            name
            for name, entry in meshes.items()
            if isinstance(entry, dict) and entry.get("host") not in (None, "", host)
        ]
        if not foreign:
            continue
        for name in foreign:
            del meshes[name]
        dump_document(path, document)
        removed[host] = sorted(foreign)
    return removed


def _peer_entries(mesh: Mesh, host: str) -> list[CommentedMap]:
    entries: list[CommentedMap] = []
    for peer in mesh.peers_of(host):
        entry = CommentedMap()
        entry["host"] = peer.host
        entry["endpoint"] = peer.endpoint or peer.host
        entry["public_key"] = peer.public_key
        entry["address"] = peer.address
        entry["allowed_ips"] = (
            (mesh.spec.routed_range or mesh.spec.subnet)
            if peer.is_hub
            else peer.address + HOST_PREFIX_32
        )
        entry["is_hub"] = peer.is_hub
        entries.append(entry)
    return entries


def write_mesh(
    mesh: Mesh,
    host_vars_dir: Path,
    vault_password_file: Path,
    application_id: str = DEFAULT_APPLICATION_ID,
) -> list[Path]:
    """Write ``mesh`` into every member's host_vars and return the paths."""
    written: list[Path] = []
    key_name = private_key_name()

    for member in mesh.members:
        path = host_vars_path(host_vars_dir, member.host)
        document = load_document(path) if path.exists() else CommentedMap()

        app = ensure_map(ensure_map(document, "applications"), application_id)
        entry = ensure_map(ensure_map(app, MESHES_KEY), mesh.spec.name)
        entry["host"] = member.host
        entry["address"] = member.address
        entry["subnet"] = mesh.spec.subnet
        entry["listen_port"] = mesh.spec.listen_port
        entry["is_hub"] = member.is_hub
        entry["public_key"] = member.public_key
        entry["peers"] = _peer_entries(mesh, member.host)

        if member.private_key is not None:
            credentials = ensure_map(ensure_map(app, SECRETS_KEY), CREDENTIALS_KEY)
            credentials[key_name] = vault_value(
                vault_password_file, member.private_key, key_name
            )

        dump_document(path, document)
        written.append(path)
    return written
