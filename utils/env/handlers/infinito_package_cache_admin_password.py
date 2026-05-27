"""INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD: stable per-host Nexus admin
password: sha256(host_path:hostname), truncated to 32 hex chars."""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

from utils.env.runtime import hostname

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD"
COMMENT = (
    "Stable per-host Nexus admin password: sha256(host_path:hostname), "
    "truncated to 32 hex chars."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    existing_pw = os.environ.get(KEY, "").strip()
    if existing_pw:
        eb.set(KEY, existing_pw, comment=COMMENT)
        return
    seed = f"{eb.get('INFINITO_CACHE_PACKAGE_HOST_PATH')}:{hostname()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
    eb.set(KEY, digest, comment=COMMENT)
