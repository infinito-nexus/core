from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any as _load_yaml_cached
from utils.docker.image.pin import pull_reference
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import is_maintained

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
RETIRED = "eol"


@dataclass(frozen=True)
class ImageRef:
    """Role-declared container image reference.

    Attributes:
        role: e.g. ``svc-db-postgres``
        service: e.g. ``postgres``
        name: canonical image name without registry, e.g. ``postgis/postgis``
        version: e.g. ``17-3.5``
        source: full pull ref, e.g. ``docker.io/library/postgres:16``
        registry: source registry hostname, e.g. ``docker.io``, ``quay.io``
        source_file: file the ref was read from, role-relative for a role
            image and repository-relative for a ``runner`` image
        derived: the ref carries a ``version_variants`` suffix rather than the
            version the service declares, so it is a tag the mirror must carry
            but never the version a role deploys

    """

    role: str
    service: str
    name: str
    version: str
    source: str
    registry: str = "docker.io"
    source_file: str = ROLE_FILE_META_SERVICES
    derived: bool = False

    @property
    def addressable(self) -> str:
        """``name`` with its registry back in front, as a probe must ask for it.

        ``name`` is stripped of the registry so roles can be compared across
        sources. A probe that passes it on reaches docker.io, where an image
        published only on ghcr.io or quay.io does not exist, and reads the
        404 as an indeterminate answer.
        """
        return f"{self.registry}/{self.name}"


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

    return pull_reference(f"docker.io/{base}", version)


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

    return pull_reference(f"{registry}/{base}", version)


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


def role_lifecycle(services: dict) -> str:
    """The role's lifecycle stage, empty when no service names one.

    Args:
        services: the parsed ``meta/services.yml`` of one role.

    Returns:
        The stage of the one entry that carries a ``lifecycle`` field, which
        is the role's primary service.
    """
    for entry in services.values():
        if isinstance(entry, dict) and entry.get("lifecycle"):
            return str(entry["lifecycle"])
    return ""


def iter_role_images(repo_root: Path) -> Iterable[ImageRef]:
    """
    Yield all ImageRef entries discovered across all roles in ``repo_root``.

    Source: ``roles/**/meta/services.yml`` -> ``<entity>.{image,version}``.

    A role whose vars derive a further tag from ``version`` lists the suffixes
    under ``<entity>.version_variants``; each yields its own ref, because this
    function is the only enumeration the mirror sees and a tag it never emits
    can never be mirrored.

    Two kinds of role are left out. One the updaters do not maintain
    (``is_maintained``), and one whose lifecycle is ``eol``: a retired role sits
    outside the lifecycle envelope ``default.env`` tests, so no deploy can reach
    its images, and its upstream is free to withdraw them. MinIO's quay tags
    answer 401 to anonymous pulls and exist nowhere else, which failed the
    mirror job on every run while nothing could have consumed the result.

    See docs/contributing/artefact/image.md for the full format reference.
    """
    roles_dir = (repo_root / "roles").resolve()

    for services_file in roles_dir.glob(f"**/{ROLE_FILE_META_SERVICES}"):
        role_name = services_file.parent.parent.name
        if not is_maintained(roles_dir, role_name):
            continue

        services = load_yaml(services_file)

        if not isinstance(services, dict):
            continue

        if role_lifecycle(services) == RETIRED:
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

            variants = service.get("version_variants")
            suffixes = [""] + [
                str(suffix)
                for suffix in (variants if isinstance(variants, list) else [])
                if str(suffix).strip()
            ]

            for suffix in suffixes:
                tag = version + suffix
                yield ImageRef(
                    role=role_name,
                    service=str(service_name),
                    name=canonical_image_name(image),
                    version=tag,
                    source=image_source(image, tag),
                    registry=_detect_registry(image),
                    source_file=ROLE_FILE_META_SERVICES,
                    derived=bool(suffix),
                )


RUNNER_ROLE = "runner"
RUNNER_COMPOSE_FILES = ("compose.yml", "compose/cache.override.yml")
RUNNER_ENV_IMAGES = ("INFINITO_CACHE_PACKAGE_FRONTEND_INIT_IMAGE",)


def _runner_image(service: str, image: str, source_file: str) -> ImageRef | None:
    base, suffix = split_name_and_suffix(image)
    if not suffix.startswith(":") or not is_mirrorable_image(base):
        return None
    version = suffix[1:]
    return ImageRef(
        role=RUNNER_ROLE,
        service=service,
        name=canonical_image_name(base),
        version=version,
        source=image_source(base, version),
        registry=_detect_registry(base),
        source_file=source_file,
    )


def iter_runner_images(repo_root: Path) -> Iterable[ImageRef]:
    """Yield the images the CI runner pulls itself, outside every role.

    Args:
        repo_root: repository root holding the RUNNER_COMPOSE_FILES and
            ``default.env``. A compose ``image`` that interpolates a variable,
            carries no tag or is pinned by digest yields nothing.
    """
    from utils.env.parser import parse_static_env

    for source_file in RUNNER_COMPOSE_FILES:
        services = load_yaml(repo_root / source_file).get("services") or {}
        for service, spec in services.items():
            image = (
                str(spec.get("image") or "").strip() if isinstance(spec, dict) else ""
            )
            if not image or "${" in image:
                continue
            ref = _runner_image(str(service), image, source_file)
            if ref is not None:
                yield ref

    declared = parse_static_env(repo_root / "default.env")
    for key in RUNNER_ENV_IMAGES:
        ref = _runner_image(key, declared[key], "default.env")
        if ref is not None:
            yield ref
