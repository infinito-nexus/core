"""INFINITO_ARTEFACT_BASE: the base a consumer fetches a pinned artefact under."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.context import BuildContext, EnvBuilder

KEY = "INFINITO_ARTEFACT_BASE"
STACK_KEY = "INFINITO_CACHE_STACK"
FRONTEND_IP_KEY = "INFINITO_CACHE_PACKAGE_FRONTEND_IP"
STATIC_READS = (KEY,)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    upstream = ctx.static.get(KEY, "")
    frontend = f"http://{eb.get(FRONTEND_IP_KEY)}"
    base = frontend if eb.get(STACK_KEY) == "true" else upstream
    eb.set(KEY, base, comment=ctx.static_comments.get(KEY, ""))
