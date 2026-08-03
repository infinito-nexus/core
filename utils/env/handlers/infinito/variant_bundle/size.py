"""INFINITO_VARIANT_BUNDLE_SIZE: how many matrix-deploy variants one CI runner
iterates before the discovery (utils.github.variant.bundles) splits a role into
another runner. Defaults to 3 everywhere."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.github.variant.limits import DEFAULT_BUNDLE_SIZE

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_VARIANT_BUNDLE_SIZE"
COMMENT = (
    "Variants per CI runner before the deploy-matrix discovery "
    "(utils.github.variant.bundles) splits a role across runners."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, str(DEFAULT_BUNDLE_SIZE), comment=COMMENT)
