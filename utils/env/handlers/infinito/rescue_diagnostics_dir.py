"""INFINITO_RESCUE_DIAGNOSTICS_DIR: rescue snapshot folder, read from the
group_vars paths SPOT (group_vars/all/05_paths.yml DIR_RESCUE_DIAGNOSTICS)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.paths import read_group_path

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_RESCUE_DIAGNOSTICS_DIR"
COMMENT = "Where rescue: blocks write their failure snapshot; CI uploads it (SPOT: group_vars/all/05_paths.yml DIR_RESCUE_DIAGNOSTICS)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, read_group_path("DIR_RESCUE_DIAGNOSTICS"), comment=COMMENT)
