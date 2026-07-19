from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any as _load_yaml_cached
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

DOCKER_HUB_PREFIXES = (
    "docker.io/",
    "registry-1.docker.io/",
    "index.docker.io/",
)

_ALL_REGISTRY_PREFIXES = (
    *DOCKER_HUB_PREFIXES,
    "quay.io/",
    "ghcr.io/",
    "mcr.microsoft.com/",
    "registry.opencode.de/",
    "registry.gitlab.com/",
)

_MIRRORABLE_REGISTRIES = frozenset(
    {
        "docker.io",
        "registry-1.docker.io",
        "index.docker.io",
        "quay.io",
        "ghcr.io",
        "mcr.microsoft.com",
        "registry.opencode.de",
        "registry.gitlab.com",
    }
)


@dataclass(frozen=True)
class ImageRef:
    """Role-declared container image reference.

    Fields:
        role: e.g. ``svc-db-postgres``
        service: e.g. ``postgres``
        name: canonical image name without registry, e.g. ``postgis/postgis``
        version: e.g. ``17-3.5``
        source: full pull ref, e.g. ``docker.io/library/postgres:16``
        registry: source registry hostname, e.g. ``docker.io``, ``quay.io``
        source_file: role-relative file the ref was read from
    """

    role: str
    service: str
    name: str
    version: str
    source: str
    registry: str = "docker.io"
    source_file: str = ROLE_FILE_META_SERVICES


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


def split_name_and_suffix(image: str) -> tuple[str, str]:
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
    base, _suffix = split_name_and_suffix(image)

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
    base, _suffix = split_name_and_suffix(bare)

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

    Source: roles/**/meta/services.yml → <entity>.{image,version}.

    See docs/contributing/artefact/image.md for the full format reference.
    """
    roles_dir = repo_root / "roles"

    for services_file in roles_dir.glob(f"**/{ROLE_FILE_META_SERVICES}"):
        role_name = services_file.parent.parent.name
        services = load_yaml(services_file)

        if not isinstance(services, dict):
            continue

        for service_name, service in services.items():
            if not isinstance(service, dict):
                continue

            image = str(service.get("image") or "").strip()
            version = str(service.get("version") or "").strip()

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
                source_file=ROLE_FILE_META_SERVICES,
            )
