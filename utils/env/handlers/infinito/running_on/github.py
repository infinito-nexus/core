"""INFINITO_RUNNING_ON_GITHUB: true when running on real GitHub Actions
(not act)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_RUNNING_ON_GITHUB"
COMMENT = "True when running on real GitHub Actions (not act)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(KEY, "true" if ctx.on_gha else "false", comment=COMMENT)
