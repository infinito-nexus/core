"""INFINITO_CACHE_UPSTREAMS: every repository the package cache proxies, as
``name|flavor|url|distribution|repodata_depth|content_max_age`` records
separated by commas, from the cache: entries the roles declare in their
meta/networks.yml.

`utils.cache.records` owns the format and the mirror resolution, so the role's
bootstrap task and this key cannot drift apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache.records import records

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_UPSTREAMS"
MIRRORS_KEY = "INFINITO_APT_UBUNTU_MIRRORS"
COMMENT = "Proxied repositories as name|flavor|url|distribution|repodata_depth|content_max_age; from the cache: declarations."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    rendered = records(eb.get(MIRRORS_KEY) or ctx.static.get(MIRRORS_KEY, ""))
    if rendered:
        eb.set(KEY, rendered, comment=COMMENT)
