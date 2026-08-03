"""Address the GHCR mirror copy of an upstream image.

Owns the mirror path formula for both the provider that writes the copies and
the registry probes that read them.
"""

from __future__ import annotations

import os
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.docker.image.ref import DOCKER_HUB_REGISTRIES, split_registry_and_name

_MIRROR_PREFIX_ENV = "INFINITO_GHCR_MIRROR_PREFIX"


def mirror_image_base(
    registry: str,
    name: str,
    *,
    namespace: str,
    repository: str,
    prefix: str,
) -> str:
    """Return the mirror repository for an upstream image, without a tag.

    Args:
        registry: normalised upstream registry host, e.g. ``docker.io``.
        name: upstream repository without the registry, e.g. ``postgis/postgis``.
        namespace: GHCR owner.
        repository: GHCR repository the mirror lives under.
        prefix: path segment separating mirrored images from own images.
    """
    return (
        f"ghcr.io/{namespace.lower()}/{repository.lower()}"
        f"/{prefix.strip('/')}/{registry}/{name}"
    )


def _normalise_registry(registry: str | None) -> str:
    if registry is None or registry in DOCKER_HUB_REGISTRIES:
        return "docker.io"
    return registry


def _config_path() -> Path:
    """Return the git config file, following the linked-worktree indirection.

    In a linked worktree ``.git`` is a file naming that worktree's gitdir, so
    reading ``.git/config`` raises NotADirectoryError and every caller silently
    loses the remote - which costs the image mirror and sends every probe to the
    upstream registry. The shared config lives in the common dir the worktree's
    ``commondir`` points at.
    """
    git = PROJECT_ROOT / ".git"
    if git.is_dir():
        return git / "config"
    gitdir = Path(read_text(str(git)).partition("gitdir:")[2].strip())
    commondir = gitdir / "commondir"
    if commondir.is_file():
        gitdir = (gitdir / read_text(str(commondir)).strip()).resolve()
    return gitdir / "config"


def _git_config() -> dict[str, str]:
    """Return ``.git/config`` as ``{"<section>.<key>": value}``.

    Hand-parsed rather than read with :mod:`configparser`, which rejects the
    duplicate keys git happily writes (two ``vscode-merge-base`` lines under one
    branch are enough to make it raise).
    """
    try:
        raw = _config_path().read_text(encoding="utf-8")  # nocheck: cache-read
    except OSError:
        return {}

    entries: dict[str, str] = {}
    section = ""
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].replace('"', "").replace(" ", ".")
            continue
        key, sep, value = stripped.partition("=")
        if sep and section:
            entries.setdefault(f"{section}.{key.strip()}", value.strip())
    return entries


def _remote_url() -> str | None:
    """Return the URL of the remote the repository publishes to.

    ``remote.pushDefault`` wins over ``origin``: CI, and therefore the mirror
    packages, live on the fork this repository pushes to, while ``origin`` may
    point at an upstream that hosts no mirror at all.
    """
    config = _git_config()
    preferred = config.get("remote.pushDefault")
    for name in (preferred, "origin"):
        if name and (url := config.get(f"remote.{name}.url")):
            return url
    return None


def _owner_and_repository() -> tuple[str, str] | None:
    """Return ``(owner, repository)`` for the GHCR namespace, or ``None``."""
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
    slug = os.environ.get("GITHUB_REPOSITORY")
    if slug and "/" in slug:
        slug_owner, _, slug_repo = slug.partition("/")
        return (owner or slug_owner).lower(), slug_repo.lower()

    url = _remote_url()
    if not url:
        return None
    path = url.removesuffix(".git")
    if "://" in path:
        path = path.split("://", 1)[1].partition("@")[2] or path.split("://", 1)[1]
        path = path.partition("/")[2]
    elif ":" in path:
        path = path.partition(":")[2]
    if "/" not in path:
        return None
    remote_owner, _, remote_repo = path.rpartition("/")
    remote_owner = remote_owner.rpartition("/")[2]
    if not remote_owner or not remote_repo:
        return None
    return (owner or remote_owner).lower(), remote_repo.lower()


def mirror_image(image: str) -> str | None:
    """Return the mirror repository for *image*, or ``None`` when unresolvable.

    ``None`` means the caller has to address the upstream registry: the image
    name is malformed, the mirror prefix is not configured, or neither the
    GitHub environment nor the git remote names the GHCR namespace.
    """
    prefix = os.environ.get(_MIRROR_PREFIX_ENV)
    if not prefix or not prefix.strip():
        return None

    parsed = split_registry_and_name(image)
    if parsed is None:
        return None

    coordinates = _owner_and_repository()
    if coordinates is None:
        return None

    namespace, repository = coordinates
    registry, name = parsed
    return mirror_image_base(
        _normalise_registry(registry),
        name,
        namespace=namespace,
        repository=repository,
        prefix=prefix.strip(),
    )
