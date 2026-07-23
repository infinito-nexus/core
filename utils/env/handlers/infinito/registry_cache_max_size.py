"""INFINITO_CACHE_REGISTRY_MAX_SIZE: registry-cache soft cap (half of
free disk at INFINITO_CACHE_REGISTRY_HOST_PATH, floor 1g)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from utils.env.runtime import df_avail_gb

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_REGISTRY_MAX_SIZE"
COMMENT = (
    "Registry-cache soft cap (half of free disk at "
    "INFINITO_CACHE_REGISTRY_HOST_PATH, floor 1g)."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    host_path = eb.get("INFINITO_CACHE_REGISTRY_HOST_PATH")
    if not host_path:
        return
    existing = os.environ.get(KEY, "").strip()
    if existing:
        eb.set(KEY, existing, comment=COMMENT)
        return
    avail = df_avail_gb(host_path) or 2
    eb.set(KEY, f"{max(avail // 2, 1)}g", comment=COMMENT)
