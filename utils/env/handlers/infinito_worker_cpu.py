"""INFINITO_WORKER_CPU: CPU-count base for the worker SPOT chain.

Resolves to ``os.cpu_count()`` when ``INFINITO_WORKER_ENABLED`` is
truthy, otherwise to ``1`` (sequential).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_WORKER_CPU"
COMMENT = "Host CPU count when INFINITO_WORKER_ENABLED truthy, else 1 (sequential)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    enabled = eb.get("INFINITO_WORKER_ENABLED").strip().lower()
    default = str(os.cpu_count() or 4) if enabled in {"1", "true", "yes", "on"} else "1"
    eb.setdefault(KEY, default, comment=COMMENT)
