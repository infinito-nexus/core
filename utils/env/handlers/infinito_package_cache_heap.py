"""INFINITO_CACHE_PACKAGE_HEAP: Nexus JVM heap size (half of MemAvailable,
cap 2g, floor 1g)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from utils.env.runtime import mem_available_mb

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_PACKAGE_HEAP"
COMMENT = "Nexus JVM heap size (half of MemAvailable, cap 2g, floor 1g)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    existing_heap = os.environ.get(KEY, "").strip()
    if existing_heap:
        eb.set(KEY, existing_heap, comment=COMMENT)
        return
    ram_mb = mem_available_mb()
    heap_gb = 1 if ram_mb <= 0 else max(1, min(ram_mb // 2048, 2))
    eb.set(KEY, f"{heap_gb}g", comment=COMMENT)
