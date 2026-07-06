"""Node Tor v3 onion identity for the harness.

:func:`ensure_node_onion` pre-mints (or reuses) the node's onion and returns its
address, storing the authoritative hidden-service key files at the repo root. The
``svc-net-tor`` role copies those keys into the running daemon so it serves exactly
that address; the inventory provisioner writes the address into
``applications.svc-net-tor.services.tor.node``. The onion is a deploy-time input;
there is no in-deploy minting (a random mint would not match the provisioned node).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from utils.tor_onion import IDENTITY_DIRNAME, identity_hs_dir, mint

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["IDENTITY_DIRNAME", "ensure_node_onion", "identity_hs_dir"]

HS_FILE_MODES = {
    "hostname": 0o600,
    "hs_ed25519_public_key": 0o600,
    "hs_ed25519_secret_key": 0o600,
}


def _write_files(directory: Path, files: dict[str, bytes]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = directory / name
        fd = os.open(
            str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, HS_FILE_MODES[name]
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)


def ensure_node_onion(base_dir: str | Path) -> str:
    """Mint (or reuse) the node onion identity and return its ``.onion`` address.

    Dual-stack model: the node keeps its clearnet ``DOMAIN_PRIMARY``; the node
    onion is an ADDITIVE address opted-in apps (``services.tor.enabled``) are also
    reachable under as ``<sub>.<node-onion>`` over Tor. Idempotent: an existing key
    at ``<base_dir>/.onion-identity/hs`` is reused so the address is stable across
    runs. The key files are the single source of truth — the ``svc-net-tor`` role
    copies them into the daemon so it serves exactly this address, and the
    inventory provisioner writes the returned address into
    ``applications.svc-net-tor.services.tor.node`` (no env indirection).
    """
    hs = identity_hs_dir(base_dir)
    hostname_file = hs / "hostname"
    if hostname_file.exists():
        return hostname_file.read_text(encoding="ascii").strip()  # nocheck: cache-read
    key = mint()
    _write_files(hs, key.files())
    return key.address
