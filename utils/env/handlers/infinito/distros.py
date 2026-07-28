"""INFINITO_DISTROS: every distro id declared in meta/distros.yml.

The key carries no static default; it is generated here so the shell and
CI side of the project read the same SPOT the Python side does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.distros import FILE_META_DISTROS, distro_names

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_DISTROS"
COMMENT = f"Space-separated distro ids, derived from {FILE_META_DISTROS}."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(KEY, " ".join(distro_names()), comment=COMMENT)
