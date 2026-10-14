"""Provision the node ``NETWORK_MODE`` from the ``network`` environment variable.

The CI network axis hands every deploy row its node network mode as
``network``, next to the ``disable`` tokens it drops providers with.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from utils.networks.reachability import NODE_MODES

from .yaml_io import dump_yaml, load_yaml

if TYPE_CHECKING:
    from pathlib import Path


def apply_network_mode_from_env(host_vars_file: Path) -> None:
    """Write ``network`` from the environment into the host_vars ``NETWORK_MODE``.

    Args:
        host_vars_file: the host_vars file of the provisioned host.

    Raises:
        SystemExit: ``network`` names no node network mode.
    """
    raw = os.environ.get("network", "").strip().lower()
    if not raw:
        return
    if raw not in NODE_MODES:
        raise SystemExit(
            f"network={raw!r} is unknown; expected {', '.join(NODE_MODES)}"
        )
    data = load_yaml(host_vars_file) if host_vars_file.exists() else {}
    if not isinstance(data, dict):
        data = {}
    data["NETWORK_MODE"] = raw
    dump_yaml(host_vars_file, data)
    print(f"[INFO] network={raw!r} → NETWORK_MODE")
