"""INFINITO_BUILD: GHA-side default -- run the published image instead of
building a local one the stack never starts."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_BUILD"


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    if not ctx.on_gha:
        return
    eb.setdefault(KEY, "0", comment=ctx.static_comments.get(KEY, ""))
