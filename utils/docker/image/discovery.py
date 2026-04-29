from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Tuple

from utils.cache.yaml import load_yaml_any as _load_yaml_cached


DOCKER_HUB_PREFIXES = (
    "docker.io/",
    "registry-1.docker.io/",
    "index.docker.io/",
)

# All registry hostname prefixes that are stripped when building the canonical name.
_ALL_REGISTRY_PREFIXES = DOCKER_HUB_PREFIXES + (
    "quay.io/",
    "ghcr.io/",
    "mcr.microsoft.com/",
)

# Registries whose images should be mirrored to GHCR.
_MIRRORABLE_REGISTRIES = frozenset(
    {
        "docker.io",
        "registry-1.docker.io",
        "index.docker.io",
        "quay.io",
        "ghcr.io",
        "mcr.microsoft.com",
    }
)


@dataclass(frozen=True)
class ImageRef:
    role: str  # e.g. svc-db-postgres
    service: str  # e.g. postgres
    name: str  # canonical image name without registry, e.g. postgis/postgis or postgres
    version: str  # e.g. 17-3.5
    source: str  # full pull ref, e.g. docker.io/library/postgres:16 or quay.io/keycloak/keycloak:latest
    registry: str = (
        "docker.io"  # source registry hostname, e.g. docker.io, quay.io, ghcr.io
    )
    source_file: str = "meta/services.yml"  # "meta/services.yml" or "defaults/main.yml"


def load_yaml(path: Path) -> dict:
    obj = _load_yaml_cached(str(path), default_if_missing={}) or {}
    return obj if isinstance(obj, dict) else {}


def _detect_registry(image: str) -> str:
    """Return the normalised registry hostname for *image*.

    Implicit Docker Hub images (e.g. ``postgres``, ``postgis/postgis``) return
    ``"docker.io"``.
    """
    image = image.strip()
    first = image.split("/", 1)[0]
    if first in ("docker.io", "registry-1.docker.io", "index.docker.io"):
        return "docker.io"
    if "." in first or ":" in first:
        return first  # e.g. "quay.io", "ghcr.io", "mcr.microsoft.com"
    return "docker.io"  # implicit Docker Hub


def _strip_registry_prefix(image: str) -> str:
    """Remove the registry prefix (if any) from *image*, return bare reference."""
    image = image.strip()
    for prefix in _ALL_REGISTRY_PREFIXES:
        if image.startswith(prefix):
            return image[len(prefix) :]
    return image


def is_docker_hub_image(image: str) -> bool:
    """Return True iff *image* is hosted on Docker Hub (kept for backward compat)."""
    return _detect_registry(image) == "docker.io"


def is_mirrorable_image(image: str) -> bool:
    """Return True for images from any supported public registry that we mirror."""
    image = image.strip()
    if not image:
        return False
    return _detect_registry(image) in _MIRRORABLE_REGISTRIES


def normalize_docker_hub(image: str) -> str:
    """Remove Docker Hub registry prefix if present (backward compat)."""
    image = image.strip()
    for prefix in DOCKER_HUB_PREFIXES:
        if image.startswith(prefix):
            return image[len(prefix) :]
    return image


def split_name_and_suffix(image: str) -> Tuple[str, str]:
    """
    Split image into base name and suffix:
      repo/name:tag   -> (repo/name, :tag)
      repo/name@sha.. -> (repo/name, @sha..)
      repo/name       -> (repo/name, "")
    """
    image = image.strip()

    if "@sha256:" in image:
        base, digest = image.split("@", 1)
        return base, f"@{digest}"

    last_slash = image.rfind("/")
    last_colon = image.rfind(":")
    if last_colon > last_slash:
        return image[:last_colon], image[last_colon:]

    return image, ""


def docker_hub_source(image: str, version: str) -> str:
    """Build canonical Docker Hub source ref for skopeo.

    postgres + 16         -> docker.io/library/postgres:16
    postgis/postgis + 17  -> docker.io/postgis/postgis:17
    """
    image = normalize_docker_hub(image)
    base, _suffix = split_name_and_suffix(image)  # drop embedded tag/digest

    if "/" not in base:
        base = f"library/{base}"

    return f"docker.io/{base}:{version}"


def image_source(image: str, version: str) -> str:
    """Full pull reference for skopeo (without the ``docker://`` scheme).

    Examples::

        postgres          + 16      -> docker.io/library/postgres:16
        postgis/postgis   + 17-3.5  -> docker.io/postgis/postgis:17-3.5
        quay.io/keycloak/keycloak + latest -> quay.io/keycloak/keycloak:latest
        ghcr.io/mastodon/mastodon + latest -> ghcr.io/mastodon/mastodon:latest
    """
    registry = _detect_registry(image)
    bare = _strip_registry_prefix(image)
    base, _suffix = split_name_and_suffix(bare)  # drop embedded tag/digest

    if registry == "docker.io" and "/" not in base:
        base = f"library/{base}"

    return f"{registry}/{base}:{version}"


def canonical_image_name(image: str) -> str:
    """Canonical image name without registry and without tag/digest.

    Strips any known registry prefix so that the name can be used uniformly
    regardless of the source registry:

        quay.io/keycloak/keycloak -> keycloak/keycloak
        ghcr.io/mastodon/mastodon -> mastodon/mastodon
        docker.io/postgres        -> postgres
        postgres                  -> postgres
    """
    bare = _strip_registry_prefix(image)
    base, _suffix = split_name_and_suffix(bare)
    return base


def iter_role_images(repo_root: Path) -> Iterable[ImageRef]:
    """
    Yield all ImageRef entries discovered across all roles in *repo_root*.

    Sources:
      1. roles/**/meta/services.yml → <entity>.{image,version}   (post-req-008)
      2. roles/**/defaults/main.yml → images.<name>.{image,version}

    See docs/contributing/artefact/image.md for the full format reference.
    """
    roles_dir = repo_root / "roles"

    # 1. Images from meta/services.yml. The file root IS the services map
    # (per req-008 file-root convention) keyed by <entity_name>.
    for services_file in roles_dir.glob("**/meta/services.yml"):
        role_name = services_file.parent.parent.name
        services = load_yaml(services_file)

        if not isinstance(services, dict):
            continue

        for service_name, service in services.items():
            if not isinstance(service, dict):
                continue

            image = (service.get("image") or "").strip()
            version = (service.get("version") or "").strip()

            if not image or not version:
                continue

            if not is_mirrorable_image(image):
                continue

            yield ImageRef(
                role=role_name,
                service=str(service_name),
                name=canonical_image_name(image),
                version=version,
                source=image_source(image, version),
                registry=_detect_registry(image),
                source_file="meta/services.yml",
            )

    # 2. Images from defaults/main.yml → images.<name>.{image,version}
    for vars_file in roles_dir.glob("**/defaults/main.yml"):
        role_name = vars_file.parent.parent.name
        data = load_yaml(vars_file)

        images = data.get("images", {})
        if not isinstance(images, dict):
            continue

        for service_name, entry in images.items():
            if not isinstance(entry, dict):
                continue

            image = (entry.get("image") or "").strip()
            version = (entry.get("version") or "").strip()

            if not image or not version:
                continue

            if not is_mirrorable_image(image):
                continue

            yield ImageRef(
                role=role_name,
                service=str(service_name),
                name=canonical_image_name(image),
                version=version,
                source=image_source(image, version),
                registry=_detect_registry(image),
                source_file="defaults/main.yml",
            )
