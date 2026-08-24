"""Provision the node onion address into ``services.tor.node``.

The onion identity (key files) is minted/reused by
``cli.administration.inventory.onion``; this provisioner is the single spot that
writes the resulting address into
``applications.svc-net-tor.services.tor.node`` of the host_vars — so consumers
read it via ``lookup('config', 'svc-net-tor', 'services.tor.node')`` with no env
indirection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cli.administration.inventory.onion import ensure_node_onion

from .yaml_io import dump_yaml, load_yaml

if TYPE_CHECKING:
    from pathlib import Path

_PROVIDER = "svc-net-tor"


def apply_tor_node_onion(
    *,
    host_vars_file: Path,
    application_ids: list[str],
    base_dir: Path,
) -> None:
    """When ``svc-net-tor`` is in the deploy, mint (or reuse) the node onion and
    set ``applications.svc-net-tor.services.tor.node`` in the host_vars."""
    if _PROVIDER not in application_ids:
        return
    address = ensure_node_onion(base_dir)
    data = load_yaml(host_vars_file) if host_vars_file.exists() else {}
    if not isinstance(data, dict):
        data = {}
    apps = data.setdefault("applications", {})
    svc = apps.setdefault(_PROVIDER, {})
    services = svc.setdefault("services", {})
    tor = services.setdefault("tor", {})
    tor["node"] = address
    dump_yaml(host_vars_file, data)
