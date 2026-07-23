"""INFINITO_DIR_BACKUPS: local backup root, derived from the var-lib SPOT
(INFINITO_DIR_VAR_LIB); mirrors group_vars/all/05_paths.yml DIR_BACKUPS."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_DIR_BACKUPS"
COMMENT = "Local backup root (derived from INFINITO_DIR_VAR_LIB)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    base = eb.get("INFINITO_DIR_VAR_LIB")
    eb.set(KEY, f"{base}/backup", comment=COMMENT)
