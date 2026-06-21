"""INFINITO_MAX_RUNTIME: deploy runtime budget consumed by the
variant-iteration guard in cli.administration.deploy.development; 6h on real
GitHub Actions, 48h otherwise."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_MAX_RUNTIME"
COMMENT = (
    "Deploy runtime budget for the variant-iteration guard "
    "(cli.administration.deploy.development): 6h on GitHub Actions, 48h otherwise."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, "6h" if ctx.on_gha else "48h", comment=COMMENT)
