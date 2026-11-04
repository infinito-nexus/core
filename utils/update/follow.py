"""Hold a Docker Hub pin to the release a moving tag points at.

A ``meta/services.yml`` entity that sets ``follow: <tag>`` only moves to a
newer tag of the same shape whose digest equals the one ``<tag>`` points at.
Ubuntu's ``latest`` names the newest LTS release and Fedora's the newest
stable one, while the higher numbers (Ubuntu's interim releases, Fedora's
rawhide) point elsewhere.
"""

from __future__ import annotations

import json

from utils.docker.image.ref import dockerhub_repo
from utils.update.base import version_depth, version_flavor, version_key
from utils.update.fetch import get


def tag_digest(image: str, tag: str) -> str:
    """Return the digest Docker Hub reports for ``image:tag``.

    Args:
        image: Docker Hub reference.
        tag: the tag to resolve.
    """
    url = f"https://hub.docker.com/v2/repositories/{dockerhub_repo(image)}/tags/{tag}"
    return str(json.loads(get(url))["digest"])


def followed_tags(
    image: str, tags: list[str], config: object, current: str
) -> list[str]:
    """Narrow *tags* to the newer releases the entity's ``follow`` tag names.

    Args:
        image: the entity's Docker Hub image.
        tags: the registry's tags for that image.
        config: one entity of ``meta/services.yml``; without ``follow`` every
            tag is kept.
        current: the pinned version.

    Returns:
        The tags unchanged without ``follow``; otherwise the newer tags of the
        pin's depth and flavor that share the followed tag's digest, and none
        when Docker Hub cannot be read.
    """
    follow = config.get("follow") if isinstance(config, dict) else None
    if follow is None:
        return tags
    newer = [
        tag
        for tag in tags
        if version_depth(tag) == version_depth(current)
        and version_flavor(tag) == version_flavor(current)
        and version_key(tag) > version_key(current)
    ]
    try:
        target = tag_digest(image, str(follow))
        return [tag for tag in newer if tag_digest(image, tag) == target]
    except (OSError, ValueError, KeyError):
        return []
