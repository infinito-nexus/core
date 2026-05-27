"""INFINITO_DOCKER_VOLUME: GHA-side override pointing at the runner's
large-disk mount."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_DOCKER_VOLUME"


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    if not ctx.on_gha:
        return
    eb.set(KEY, "/mnt/docker", comment=ctx.static_comments.get(KEY, ""))
