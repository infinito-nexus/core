"""INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX: Nexus blobstore quota (half of
free disk at INFINITO_CACHE_PACKAGE_HOST_PATH, floor 2g)."""

from __future__ import annotations

import os
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
    existing_blob = os.environ.get(KEY, "").strip()
    if existing_blob:
        eb.set(KEY, existing_blob, comment=COMMENT)
        return
    avail = df_avail_gb(eb.get("INFINITO_CACHE_PACKAGE_HOST_PATH")) or 4
    eb.set(KEY, f"{max(avail // 2, 2)}g", comment=COMMENT)
