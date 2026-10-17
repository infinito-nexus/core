"""INFINITO_GHCR_MIRROR: whether image references are rewritten to the GHCR mirror."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_GHCR_MIRROR"
COMMENT = "True where images come from the GHCR mirror instead of their upstream registry (real GitHub Actions)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(KEY, "true" if ctx.on_gha else "false", comment=COMMENT)
