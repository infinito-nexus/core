"""INFINITO_CONTAINER: compose service container name derived from
INFINITO_DISTRO. Always overrides whatever the static-env default was."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CONTAINER"
COMMENT = "Compose service container name derived from INFINITO_DISTRO."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    distro = eb.get("INFINITO_DISTRO")
    eb.set(KEY, f"infinito_nexus_{distro}", comment=COMMENT)
