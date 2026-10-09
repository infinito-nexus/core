"""INFINITO_CACHE_STACK: whether the pull-through cache stack should run."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_STACK"
COMMENT = "True where a persistent pull-through cache stack pays off (local dev)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    on_ci = ctx.on_gha or ctx.on_act or os.environ.get("CI") == "true"
    eb.set(KEY, "false" if on_ci else "true", comment=COMMENT)
