"""INFINITO_DIR_VAR_LIB: Infinito state/secrets base dir, read from the
group_vars paths SPOT (group_vars/all/05_paths.yml DIR_VAR_LIB)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.paths import read_group_path

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_DIR_VAR_LIB"
COMMENT = "Base state dir; env build derives paths from it (SPOT: group_vars/all/05_paths.yml DIR_VAR_LIB)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, read_group_path("DIR_VAR_LIB"), comment=COMMENT)
