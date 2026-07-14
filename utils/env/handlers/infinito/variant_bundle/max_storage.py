"""INFINITO_VARIANT_BUNDLE_MAX_STORAGE: cumulative min_storage budget per CI
runner before the discovery (utils.github.variant_bundles) splits a role onto
another runner — so storage-heavy variants are not stacked onto one runner that
then runs too long. Defaults to ``variant_bundles.DEFAULT_MAX_STORAGE``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.github.variant_bundles import DEFAULT_MAX_STORAGE

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_VARIANT_BUNDLE_MAX_STORAGE"
COMMENT = (
    "Cumulative min_storage per CI runner before the deploy-matrix discovery "
    "(utils.github.variant_bundles) splits a role across runners."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, DEFAULT_MAX_STORAGE, comment=COMMENT)
