from __future__ import annotations

import re
from typing import Any

DOCKER_HUB_REGISTRIES = frozenset(
    {"docker.io", "registry-1.docker.io", "index.docker.io"}
)
GHCR_REGISTRY = "ghcr.io"
MCR_REGISTRY = "mcr.microsoft.com"

# Docker image reference (name only, WITHOUT tag/digest).
IMAGE_NAME_RE = re.compile(
    r"^"
    r"("  # optional registry
    r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)"
    r"(?:\.(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?))*"
    r"(?:\:[0-9]{1,5})?"
    r"/"
    r")?"
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
    r"$"
)


def is_valid_image_name(image: Any) -> bool:
    if not isinstance(image, str):
        return False
    image = image.strip()
    if not image or " " in image or "@" in image:
        return False

    # Reject repo:tag while still allowing registry hosts with a port.
    if image.rfind(":") > image.rfind("/"):
        return False

    return IMAGE_NAME_RE.fullmatch(image) is not None


def split_registry_and_name(image: str) -> tuple[str | None, str] | None:
    """Return (registry, repository_name) for a validated Docker image name."""
    image = image.strip()
    if not is_valid_image_name(image):
        return None

    first, sep, rest = image.partition("/")
    if not sep:
        return None, image

    if "." in first or ":" in first or first == "localhost":
        return first, rest

    return None, image
