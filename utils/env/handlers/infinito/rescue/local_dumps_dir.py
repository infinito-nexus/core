"""INFINITO_RESCUE_LOCAL_DUMPS_DIR: where in-play role dumps land, read from
the group_vars paths SPOT (group_vars/all/05_paths.yml DIR_RESCUE_DIAGNOSTICS).

Distinct from INFINITO_RESCUE_DIAGNOSTICS_DIR, which the CI callers override
per invocation to name one snapshot's output root.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.paths import read_group_path

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_RESCUE_LOCAL_DUMPS_DIR"
COMMENT = "Where in-play role dumps land; the rescue collector ships them as local-dumps (SPOT: group_vars/all/05_paths.yml DIR_RESCUE_DIAGNOSTICS)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, read_group_path("DIR_RESCUE_DIAGNOSTICS"), comment=COMMENT)
