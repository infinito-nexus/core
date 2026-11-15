from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.context import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_HOST_SYNC"
STATIC_READS = (KEY,)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(
        KEY, ctx.static.get(KEY, ""), comment=ctx.static_comments.get(KEY, "")
    )
