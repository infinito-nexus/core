"""INFINITO_CACHE_HOSTS: the hostnames the package cache fronts, collected
from the ``cache:`` declarations every role makes in its meta/networks.yml."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache.hosts import declarations

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_HOSTS"
COMMENT = (
    "Hostnames the package cache fronts; derived from the roles' cache: declarations."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(KEY, ",".join(entry.host for entry in declarations().hosts), comment=COMMENT)
