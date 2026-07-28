"""INFINITO_IMAGE: fully-qualified GHCR image reference assembled from
owner, repo, distro and tag (GHA-only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.distros import environment_image

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_IMAGE"
COMMENT = (
    "Fully-qualified GHCR image reference assembled from owner, repo, distro and tag."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    if not ctx.on_gha:
        return
    owner = eb.get("GITHUB_REPOSITORY_OWNER")
    repo_name = eb.get("INFINITO_IMAGE_REPOSITORY")
    distro = eb.get("INFINITO_DISTRO")
    tag = eb.get("INFINITO_IMAGE_TAG")
    eb.setdefault(
        KEY,
        environment_image(distro, owner=owner, repository=repo_name, tag=tag),
        comment=COMMENT,
    )
