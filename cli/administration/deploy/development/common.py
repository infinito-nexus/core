"""Shared helpers for the development deploy CLI.

``DEV_INVENTORY_VARS_FILE`` mirrors ``INFINITO_INVENTORY_VARS_FILE``
from ``default.env``; the pairing is drift-guarded.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from . import PROJECT_ROOT
from .env import resolve_distro

if TYPE_CHECKING:
    from .compose import Compose


DEV_INVENTORY_VARS_FILE: str = (
    os.environ.get("INFINITO_INVENTORY_VARS_FILE")
    or "inventories/development/default.yml"
)


def resolve_container() -> str:
    """Return INFINITO_CONTAINER; raise SystemExit if unset."""
    container = os.environ["INFINITO_CONTAINER"].strip()
    if not container:
        raise SystemExit(
            "INFINITO_CONTAINER is not set. Run 'make dotenv' (or source scripts/meta/env/load.sh) "
            "before invoking cli.administration.deploy.development."
        )
    return container


def make_compose() -> Compose:
    from .compose import Compose

    distro = resolve_distro()
    resolve_container()
    return Compose(repo_root=PROJECT_ROOT, distro=distro)
