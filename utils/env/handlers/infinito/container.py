"""INFINITO_CONTAINER: compose service container name derived from
INFINITO_DISTRO. Always overrides whatever the static-env default was.

When COMPOSE_PROJECT_NAME is set to a non-default value (e.g. "runner-1"
for self-hosted runner instances), the project name is incorporated so
runner CI jobs don't conflict with the always-running dev container."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CONTAINER"
COMMENT = "Compose service container name derived from INFINITO_DISTRO."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    distro = eb.get("INFINITO_DISTRO")
    project = eb.get("COMPOSE_PROJECT_NAME")
    if project and project != "infinito-nexus":
        safe = project.replace("-", "_").replace(".", "_")
        name = f"infinito_{safe}_nexus_{distro}"
    else:
        name = f"infinito_nexus_{distro}"
    eb.set(KEY, name, comment=COMMENT)
