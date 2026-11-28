"""INFINITO_CACHE_TLS_HOSTS: the hostnames the package-cache frontend needs a
leaf certificate for, being those its cache: declarations serve over HTTPS."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache.hosts import declarations

if TYPE_CHECKING:
    from utils.env.context import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_TLS_HOSTS"
COMMENT = "Hostnames the cache frontend needs a leaf cert for; derived from the roles' cache: declarations."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(
        KEY,
        " ".join(entry.host for entry in declarations().hosts if entry.tls()),
        comment=COMMENT,
    )
