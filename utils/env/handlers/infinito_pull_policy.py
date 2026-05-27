"""INFINITO_PULL_POLICY: GHA-side override -- always pull the published
image instead of trusting whatever is cached on the runner."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_PULL_POLICY"


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    if not ctx.on_gha:
        return
    eb.set(KEY, "always", comment=ctx.static_comments.get(KEY, ""))
