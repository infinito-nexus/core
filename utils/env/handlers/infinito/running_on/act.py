"""INFINITO_RUNNING_ON_ACT: true when running under nektos/act locally."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_RUNNING_ON_ACT"
COMMENT = "True when running under nektos/act locally."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(KEY, "true" if ctx.on_act else "false", comment=COMMENT)
