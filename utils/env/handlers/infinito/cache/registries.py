"""INFINITO_CACHE_REGISTRIES: the registries the pull-through proxy bumps.

``rpardini/docker-registry-proxy`` SSL-bumps and caches only the registries
named in its ``REGISTRIES`` env; Docker Hub is hardcoded in its entrypoint. A
registry the list omits is still tunnelled, so its pulls succeed at full
upstream cost and leave no line in the proxy log - the omission is invisible
until someone times a deploy.

Deriving the list from every ``image:`` in ``roles/**/meta/services.yml``
keeps it complete by construction: a role that adopts an image from a new
registry brings that registry with it. ``BASE`` carries the registries that
were configured before this was derived and that no role image names, so
turning the list into a derived one cannot silently drop them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.docker.image.discovery import iter_role_images
from utils.docker.image.ref import DOCKER_HUB_REGISTRIES

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_REGISTRIES"
COMMENT = "Registries the pull-through proxy SSL-bumps and caches; derived from every role image, Docker Hub is implicit."

BASE = frozenset({"gcr.io", "registry.k8s.io"})


def declared_registries() -> list[str]:
    """Return every registry the cache must bump, sorted.

    Docker Hub is excluded: the proxy's entrypoint always bumps
    ``registry-1.docker.io`` and ``auth.docker.io``, and naming a Hub alias
    here would only duplicate that.
    """
    found = {
        image.registry
        for image in iter_role_images(PROJECT_ROOT)
        if image.registry and image.registry not in DOCKER_HUB_REGISTRIES
    }
    return sorted(found | BASE)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(KEY, " ".join(declared_registries()), comment=COMMENT)
