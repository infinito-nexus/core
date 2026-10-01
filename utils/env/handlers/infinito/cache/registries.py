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

The scan is a stdlib line parse rather than a YAML load. This module is
imported by the ``.env`` generator, which runs on the bare bootstrap python
before any dependency is installed, so it must not reach PyYAML - directly or
through ``utils.cache.yaml``. Only the ``image:`` value is needed and it is
always a plain scalar, so a line match is sufficient; a value carrying Jinja
is skipped, because its registry is not knowable before the templar runs.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.docker.image.ref import DOCKER_HUB_REGISTRIES, split_registry_and_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_REGISTRIES"
COMMENT = "Registries the pull-through proxy SSL-bumps and caches; derived from every role image, Docker Hub is implicit."

BASE = frozenset({"gcr.io", "registry.k8s.io"})

_IMAGE_LINE = re.compile(r"^\s*image:\s*(?P<value>\S+)")


def _image_values() -> set[str]:
    """Return every literal ``image:`` value declared under ``roles/``."""
    values: set[str] = set()
    for path in sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")):
        try:
            text = read_text(str(path))
        except (OSError, UnicodeDecodeError):
            continue
        for line in text.splitlines():
            match = _IMAGE_LINE.match(line)
            if not match:
                continue
            value = match.group("value").strip("\"'")
            if value and "{" not in value:
                values.add(value)
    return values


def declared_registries() -> list[str]:
    """Return every registry the cache must bump, sorted.

    Docker Hub is excluded: the proxy's entrypoint always bumps
    ``registry-1.docker.io`` and ``auth.docker.io``, and naming a Hub alias
    here would only duplicate that.
    """
    found: set[str] = set()
    for value in _image_values():
        parts = split_registry_and_name(value)
        if parts is None:
            continue
        registry = parts[0]
        if registry and registry not in DOCKER_HUB_REGISTRIES:
            found.add(registry)
    return sorted(found | BASE)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(KEY, " ".join(declared_registries()), comment=COMMENT)
