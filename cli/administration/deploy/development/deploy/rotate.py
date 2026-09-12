"""Credential rotation between PASS 1 and PASS 2 of a matrix-deploy round."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cli.administration.deploy.development.compose import Compose

ROTATION_EXEMPT = ("administrator",)


def _rotate_credentials(
    compose: Compose, *, inventory_dir: str, round_variants: dict[str, int]
) -> None:
    """Regenerate the round's inventory credentials before the async pass.

    Args:
        compose: the development stack the inventory lives in.
        inventory_dir: the round's inventory directory.
        round_variants: variant index per app, as baked by `init`.

    PASS 2 otherwise reads the exact values PASS 1 wrote, so nothing in the
    deploy ever has to propagate a changed secret. `administrator` stays
    exempt: its password is `ansible_become_password`, and rotating it would
    lock the deploy out of its own host.
    """
    print("=== matrix-deploy: rotating credentials between passes ===")
    compose.exec(
        [
            "infinito",
            "administration",
            "inventory",
            "credentials",
            "reset",
            "--inventory-dir",
            inventory_dir,
            "--schema",
            "--users",
            "--app-variants",
            json.dumps(round_variants, sort_keys=True),
            "--backup",
            "--except",
            *ROTATION_EXEMPT,
        ],
        check=True,
        workdir=os.environ["INFINITO_SRC_DIR"],
    )
