from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .pin import ROOT_KEY as PIN_ROOT_KEY

if TYPE_CHECKING:
    from utils.env.context import EnvBuilder

KEY = "INFINITO_CACHE_PACKAGE_FRONTEND_CONF"
COMMENT = "Upstream map the cache frontend mounts, installed from the pinned commit by `make cache-apply`."
RELATIVE = Path("compose") / "package-cache-frontend" / "upstreams.conf"
NAME = RELATIVE.name


def finalize(eb: EnvBuilder) -> None:
    eb.set(KEY, str(Path(eb.get(PIN_ROOT_KEY)) / NAME), comment=COMMENT)
