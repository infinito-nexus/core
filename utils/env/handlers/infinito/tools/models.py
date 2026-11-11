"""INFINITO_TOOLS_MODELS_HOST_PATH: node-local directory the tools lane keeps
its downloaded models in.

A model is content-addressed and re-downloadable, so it belongs beside the
package and registry caches rather than in a docker volume: a bind survives
the runner, its volumes and an image rebuild, and every node keeps its own
copy instead of dragging gigabytes across a shared filesystem.

The lane's inner docker resolves a bind against the runner's filesystem, so
``compose/tools.override.yml`` mounts this path into the runner under the same
name and ``inventories/development/tools.yml.j2`` points the roles at it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.env.handlers.infinito.cache.paths import base

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_TOOLS_MODELS_HOST_PATH"
COMMENT = "Node-local directory the tools lane keeps its downloaded models in."
SEGMENT = "models"


def default() -> str:
    """Return the models directory below the cache base the SPOT defines."""
    return str(base() / SEGMENT)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, default(), comment=COMMENT)
