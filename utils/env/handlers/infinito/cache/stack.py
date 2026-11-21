"""INFINITO_CACHE_STACK: whether the pull-through cache stack should run.

A ``custom.env`` value is read here, before the artefact base and the package
cache URL derive from the switch: the builder applies ``custom.env`` only
after every handler, so a switch set there would otherwise flip alone and
leave both pointing at a stack that does not run. An exported value is not
adopted, because ``scripts/meta/env/load.sh`` exports the previous ``.env``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from utils.env.parser import custom_env_value

if TYPE_CHECKING:
    from utils.env.context import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_STACK"
COMMENT = "True where a persistent pull-through cache stack pays off (local dev)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    on_ci = ctx.on_gha or ctx.on_act or os.environ.get("CI") == "true"
    derived = "false" if on_ci else "true"
    eb.set(KEY, custom_env_value(ctx.repo_root, KEY) or derived, comment=COMMENT)
