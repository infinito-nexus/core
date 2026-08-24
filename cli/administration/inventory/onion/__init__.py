"""Node Tor v3 onion identity for the harness.

:func:`ensure_node_onion` pre-mints (or reuses) the node's onion and returns its
address, storing the authoritative hidden-service key files at the repo root. The
``svc-net-tor`` role copies those keys into the running daemon so it serves exactly
that address; the inventory provisioner writes the address into
``applications.svc-net-tor.services.tor.node``. The onion is a deploy-time input;
there is no in-deploy minting (a random mint would not match the provisioned node).
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from utils.tor_onion import IDENTITY_DIRNAME, identity_hs_dir, mint

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


def _hand_to_checkout_owner(base_dir: Path) -> None:
    """Give the identity tree back to whoever owns the checkout.

    The provisioner may run privileged -- as root inside the DiD on a bind
    mount, or under sudo -- while the swarm playbook's `tar` that packs the
    repo for the nodes runs as the workspace user. Keys minted 0600 and owned
    by root make that tar abort with EACCES on all three files, so ownership
    has to follow the tree, not the process that happened to mint them. A
    no-op unless we are root and the checkout belongs to somebody else.

    ``lchown`` rather than ``chown``: ``rglob`` yields symlinks too, and
    following one would hand ownership of its target away instead. A path that
    vanishes between the walk and the call is skipped rather than aborting the
    provisioner -- the identity we care about is the one we just wrote.
    """
    if os.geteuid() != 0:
        return
    owner = base_dir.stat()
    if owner.st_uid == 0:
        return
    identity = base_dir / IDENTITY_DIRNAME
    for path in (identity, *identity.rglob("*")):
        with contextlib.suppress(FileNotFoundError):
            os.lchown(path, owner.st_uid, owner.st_gid)


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
    base = Path(base_dir)
    hs = identity_hs_dir(base)
    hostname_file = hs / "hostname"
    if hostname_file.exists():
        _hand_to_checkout_owner(base)
        return hostname_file.read_text(encoding="ascii").strip()  # nocheck: cache-read
    key = mint()
    _write_files(hs, key.files())
    _hand_to_checkout_owner(base)
    return key.address
