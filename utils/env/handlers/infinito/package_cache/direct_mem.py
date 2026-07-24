"""INFINITO_CACHE_PACKAGE_DIRECT_MEM: Nexus direct-memory budget; tied to
INFINITO_CACHE_PACKAGE_HEAP."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_PACKAGE_DIRECT_MEM"
COMMENT = "Nexus direct-memory budget; tied to INFINITO_CACHE_PACKAGE_HEAP."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, eb.get("INFINITO_CACHE_PACKAGE_HEAP"), comment=COMMENT)
