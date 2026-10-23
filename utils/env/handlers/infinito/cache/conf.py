"""INFINITO_CACHE_PACKAGE_FRONTEND_CONF: nginx upstream map the shared
package-cache frontend mounts.

Every checkout renders its own, so a branch that declares a new cache host
serves it instead of reading a map that cannot know about it. `make
cache-apply` installs that map into the running frontend.

The map itself is generated, never tracked, so no second copy of a hostname
can drift; ``utils.cache.render.render_artifacts`` writes it once the
value-set is built.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_PACKAGE_FRONTEND_CONF"
COMMENT = "Upstream map the cache frontend mounts, rendered by this checkout."
RELATIVE = Path("compose") / "package-cache-frontend" / "upstreams.conf"


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, str(ctx.repo_root / RELATIVE), comment=COMMENT)
