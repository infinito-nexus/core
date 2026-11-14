from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_LINT_RUNNER"


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    if not (ctx.on_gha or ctx.on_act):
        return
    eb.setdefault(KEY, "host", comment=ctx.static_comments.get(KEY, ""))
