from __future__ import annotations

from typing import TYPE_CHECKING

from utils.env.handlers.infinito.cache.paths import base

if TYPE_CHECKING:
    from utils.env.context import BuildContext, EnvBuilder

GRACE_KEY = "INFINITO_TOOLS_IDLE_GRACE"
STAMP_DIR_KEY = "INFINITO_TOOLS_STAMP_DIR"
GRACE = "2h"
GRACE_COMMENT = "How long the tools services stay up after the last tools target ended."
STAMP_COMMENT = "Machine-wide directory every tools target stamps its runs in."
SEGMENT = "tools"


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(GRACE_KEY, GRACE, comment=GRACE_COMMENT)
    eb.setdefault(STAMP_DIR_KEY, str(base() / SEGMENT), comment=STAMP_COMMENT)
