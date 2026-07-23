"""INFINITO_WORKER_FETCH: I/O-bound network-fetch worker count.

INFINITO_WORKER_CPU * 20, with a base of 1 collapsing to 1 (the
operator's sequential-fallback signal). Consumed by URL probers and
upstream tag fetchers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_WORKER_FETCH"
COMMENT = "Workers for network-bound bulk fetches (INFINITO_WORKER_CPU * 20)."
_FACTOR = 20


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    base = int(eb.get("INFINITO_WORKER_CPU") or "1")
    default = str(base * _FACTOR) if base > 1 else "1"
    eb.setdefault(KEY, default, comment=COMMENT)
