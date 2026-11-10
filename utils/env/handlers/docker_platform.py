"""INFINITO_DOCKER_PLATFORM: target the architecture this deploy was assigned."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_DOCKER_PLATFORM"
COMMENT = "Platform the deploy creates app containers for; empty: the host's own."

SOURCE_KEY = "INFINITO_ARCHITECTURE"


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    architecture = (eb.get(SOURCE_KEY) or "").strip()
    if not architecture:
        eb.setdefault(KEY, "", comment=COMMENT)
        return
    platform = f"linux/{architecture}"
    named = (eb.get(KEY) or "").strip()
    if named and named != platform:
        raise ValueError(
            f"{KEY}={named!r} contradicts {SOURCE_KEY}={architecture!r}, which "
            f"implies {platform!r}. Drop one of them: the architecture is the "
            f"axis, the platform is what it means to docker."
        )
    eb.set(KEY, platform, comment=COMMENT)
