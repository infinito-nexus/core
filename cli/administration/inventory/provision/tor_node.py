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

from .ruamel_io import dump_document, ensure_map, load_document

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
    document = load_document(host_vars_file)
    apps = ensure_map(document, "applications")
    services = ensure_map(ensure_map(apps, _PROVIDER), "services")
    ensure_map(services, "tor")["node"] = address
    dump_document(host_vars_file, document)
