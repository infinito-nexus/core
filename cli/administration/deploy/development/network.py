from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

DOCKER_DAEMON_CONFIG_PATH = Path("/etc/docker/daemon.json")
MIN_VALID_MTU = 576
MAX_VALID_MTU = 9000


def detect_outer_network_mtu(
    env: Mapping[str, str] | None = None,
    *,
    daemon_config_path: Path = DOCKER_DAEMON_CONFIG_PATH,
) -> str | None:
    current_env = os.environ if env is None else env
    explicit_mtu = current_env["INFINITO_OUTER_NETWORK_MTU"].strip()
    if explicit_mtu:
        return explicit_mtu

    if not daemon_config_path.exists():
        return None

    try:
        # nocheck below: single-shot CLI read; tests mock Path.read_text directly
        raw = daemon_config_path.read_text()  # nocheck: cache-read
        daemon_config = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return None

    mtu = daemon_config.get("mtu")
    if isinstance(mtu, int) and MIN_VALID_MTU <= mtu <= MAX_VALID_MTU:
        return str(mtu)

    return None
