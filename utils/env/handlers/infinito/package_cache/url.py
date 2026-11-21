"""INFINITO_CACHE_PACKAGE_URL: the package cache's Nexus root on the infra network.

A run fact, written through ``eb.set``: it follows ``INFINITO_CACHE_STACK``
and the runner address on every ``make dotenv``, so a value an earlier run
wrote never survives a stack that went off. ``custom.env`` still wins, and an
exporting shell wins for its own run through ``load.sh``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.context import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_PACKAGE_URL"
STACK_KEY = "INFINITO_CACHE_STACK"
IP_KEY = "INFINITO_CACHE_PACKAGE_IP"
PORT_KEY = "INFINITO_CACHE_PACKAGE_PORT"
COMMENT = "Nexus root of the package cache while the cache stack runs; empty otherwise."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    url = (
        f"http://{eb.get(IP_KEY)}:{eb.get(PORT_KEY)}"
        if eb.get(STACK_KEY) == "true"
        else ""
    )
    eb.set(KEY, url, comment=COMMENT)
