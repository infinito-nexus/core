"""INFINITO_DNS53_SAMPLER_LOG: :53 sampler log, read from the group_vars
paths SPOT (group_vars/all/05_paths.yml FILE_DNS53_SAMPLER_LOG)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.paths import read_group_path

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_DNS53_SAMPLER_LOG"
COMMENT = "Where the :53 sampler appends its ticks and the rescue collector reads them (SPOT: group_vars/all/05_paths.yml FILE_DNS53_SAMPLER_LOG)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, read_group_path("FILE_DNS53_SAMPLER_LOG"), comment=COMMENT)
