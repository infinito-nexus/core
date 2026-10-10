"""Point the images the CI runner pulls itself at their GHCR mirror."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from cli.contributing.mirror.providers import GHCRProvider
from utils.cache.yaml import dump_yaml
from utils.docker.image.discovery import iter_runner_images

if TYPE_CHECKING:
    from pathlib import Path

OVERRIDE = "build/compose/runner-mirror.override.yml"


def mirrored_images(repo_root: Path) -> dict[tuple[str, str], str]:
    """Return ``{(source_file, service): mirror reference}`` for every runner image.

    Args:
        repo_root: repository root the runner images are declared under.
    """
    provider = GHCRProvider(
        os.environ["GITHUB_REPOSITORY_OWNER"],
        os.environ["GITHUB_REPOSITORY"].split("/", 1)[-1],
        os.environ["INFINITO_GHCR_MIRROR_PREFIX"],
    )
    return {
        (
            image.source_file,
            image.service,
        ): f"{provider.image_base(image)}:{image.version}"
        for image in iter_runner_images(repo_root)
    }


def write_override(repo_root: Path, layered: list[str]) -> str:
    """Write the compose override that swaps the runner's images for mirrors.

    Args:
        repo_root: repository root the compose files are relative to.
        layered: compose files the stack is built from. Only their services
            are overridden, so the override never adds a service of its own.

    Returns:
        The override path relative to ``repo_root``.
    """
    services = {
        service: {"image": reference}
        for (source_file, service), reference in mirrored_images(repo_root).items()
        if source_file in layered
    }
    target = repo_root / OVERRIDE
    staging = target.with_name(f"{target.name}.{os.getpid()}")
    dump_yaml(staging, {"services": services})
    staging.replace(target)
    return OVERRIDE


def env_image(repo_root: Path, key: str) -> str:
    """Return the mirror reference for an image ``default.env`` declares.

    Args:
        repo_root: repository root holding ``default.env``.
        key: the ``default.env`` key naming the image.
    """
    return mirrored_images(repo_root)[("default.env", key)]
