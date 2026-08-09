"""INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX: Nexus blobstore quota (half of
free disk at INFINITO_CACHE_PACKAGE_HOST_PATH, floor 2g)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.env.runtime import df_avail_gb

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX"
COMMENT = (
    "Nexus blobstore quota (half of free disk at "
    "INFINITO_CACHE_PACKAGE_HOST_PATH, floor 2g)."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    avail = df_avail_gb(eb.get("INFINITO_CACHE_PACKAGE_HOST_PATH")) or 4
    eb.setdefault(KEY, f"{max(avail // 2, 2)}g", comment=COMMENT)
