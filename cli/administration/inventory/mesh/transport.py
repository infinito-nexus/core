from __future__ import annotations

import shlex
from configparser import ConfigParser
from typing import TYPE_CHECKING

from cli.administration.inventory.provision.ruamel_io import (
    dump_document,
    load_document,
)
from utils import PROJECT_ROOT
from utils.networks.mesh import address_on

from .write import host_vars_path

if TYPE_CHECKING:
    from pathlib import Path

SSH_CONNECTION = "ssh"

MESH_CONTROL_PERSIST = "600s"

_REPLACED_OPTIONS = ("ControlPersist=", "ControlPath=")


def mesh_ssh_args(base: str, *, persist: str = MESH_CONTROL_PERSIST) -> str:
    """The repo's ``ssh_args`` retuned for a host reached over the mesh.

    Args:
        base: the ``ssh_args`` every other host uses.
        persist: how long to keep an idle master alive.
    """
    words = shlex.split(base)
    kept: list[str] = []
    index = 0
    while index < len(words):
        if words[index] == "-o" and index + 1 < len(words):
            if not words[index + 1].startswith(_REPLACED_OPTIONS):
                kept += ["-o", words[index + 1]]
            index += 2
            continue
        kept.append(words[index])
        index += 1
    kept += ["-o", f"ControlPersist={persist}"]
    return shlex.join(kept)


def repo_ssh_args(config_file: Path | None = None) -> str:
    parser = ConfigParser(interpolation=None)
    parser.read(config_file or PROJECT_ROOT / "ansible.cfg")
    return parser.get("ssh_connection", "ssh_args", fallback="")


def mesh_address(host_vars_dir: Path, host: str, mesh_name: str) -> str | None:
    path = host_vars_path(host_vars_dir, host)
    if not path.exists():
        return None
    address = address_on(load_document(path).get("applications", {}), host, mesh_name)
    return address or None


def switch_to_mesh(
    host_vars_dir: Path,
    hosts: list[str],
    mesh_name: str,
    *,
    user: str,
    private_key_file: str,
) -> dict[str, str]:
    """Point every member of *mesh_name* at its mesh address over SSH.

    Returns:
        Host to the address it was switched to; a host without one is left
        alone.
    """
    switched: dict[str, str] = {}
    for host in hosts:
        address = mesh_address(host_vars_dir, host, mesh_name)
        if address is None:
            continue
        path = host_vars_path(host_vars_dir, host)
        document = load_document(path)
        document["ansible_host"] = address
        document["ansible_connection"] = SSH_CONNECTION
        document["ansible_user"] = user
        document["ansible_ssh_private_key_file"] = private_key_file
        document["ansible_ssh_args"] = mesh_ssh_args(repo_ssh_args())
        document["ansible_ssh_use_tty"] = False
        dump_document(path, document)
        switched[host] = address
    return switched
