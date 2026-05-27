"""GHA-only static-env passthrough: keys from default.env that are
only seeded when running on real GitHub Actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

STATIC_KEYS = ("INFINITO_GHCR_MIRROR_PREFIX",)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    if not ctx.on_gha:
        return
    for key in STATIC_KEYS:
        if key in ctx.static:
            eb.setdefault(
                key, ctx.static[key], comment=ctx.static_comments.get(key, "")
            )
