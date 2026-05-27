"""Inventory resolution: one helper-script call yields INFINITO_INVENTORY_DIR,
INFINITO_INVENTORY_FILE and INFINITO_INVENTORY_HOST_VARS_FILE. Kept
together because the latter two are derived path-joins on the first."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from utils.env.runtime import run_helper

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

INVENTORY_DIR_KEY = "INFINITO_INVENTORY_DIR"
INVENTORY_FILE_KEY = "INFINITO_INVENTORY_FILE"
HOST_VARS_FILE_KEY = "INFINITO_INVENTORY_HOST_VARS_FILE"

INVENTORY_DIR_COMMENT = (
    "Inventory root resolved by scripts/inventory/resolve.sh based on "
    "RUNNING_ON_* flags."
)
INVENTORY_FILE_COMMENT = "Generated devices file inside INFINITO_INVENTORY_DIR."
HOST_VARS_FILE_COMMENT = (
    "Generated host_vars/localhost.yml inside INFINITO_INVENTORY_DIR."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    inventory_dir = os.environ.get(
        "INFINITO_INVENTORY_DIR", ""
    ).strip()  # nocheck: handler-bootstrap-read
    if not inventory_dir:
        inventory_dir = run_helper(
            ["bash", "scripts/inventory/resolve.sh"],
            cwd=ctx.repo_root,
            extra_env={
                "INFINITO_RUNNING_ON_ACT": eb.get("INFINITO_RUNNING_ON_ACT"),
                "INFINITO_RUNNING_ON_GITHUB": eb.get("INFINITO_RUNNING_ON_GITHUB"),
            },
        )
    if inventory_dir:
        eb.set(INVENTORY_DIR_KEY, inventory_dir, comment=INVENTORY_DIR_COMMENT)
        eb.set(
            INVENTORY_FILE_KEY,
            f"{inventory_dir}/devices.yml",
            comment=INVENTORY_FILE_COMMENT,
        )
        eb.set(
            HOST_VARS_FILE_KEY,
            f"{inventory_dir}/host_vars/localhost.yml",
            comment=HOST_VARS_FILE_COMMENT,
        )
