"""Distribution SPOT.

``meta/distros.yml`` declares every distribution the project builds, tests
and deploys on: the id used as ``INFINITO_DISTRO``, the ``os_family``
ansible reports for it, the Galaxy platform name, the upstream base image
the development-environment matrix boots it from, and the templates the
pkgmgr base image and the environment image references are rendered from.

Consumers MUST read the distro set through this module. A local tuple of
distro names or an f-string spelling out ``ghcr.io/.../pkgmgr-...`` is a
second source of truth and drifts; ``tests/lint/repository/test_distros_spot.py``
guards against reintroducing one.

Registry owner, repository and tag are *not* declared here — they stay in
``default.env``, which is their SPOT. This module only renders them into
the templates.

Keep this module free of Ansible imports and cheap to import: it is pulled
in by the env layer and by ``utils.packages.schema``, which reach contexts
where Ansible is not installed.
"""

from __future__ import annotations

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml

FILE_META_DISTROS: str = "meta/distros.yml"

IMAGE_PKGMGR = "pkgmgr"
IMAGE_PKGMGR_VIRGIN = "pkgmgr_virgin"
IMAGE_ENVIRONMENT = "environment"


class UnknownDistroError(ValueError):
    """Raised for a distro id that ``meta/distros.yml`` does not declare."""


def _doc() -> dict:
    return load_yaml(str(PROJECT_ROOT / FILE_META_DISTROS))


def _specs() -> dict[str, dict]:
    return _doc()["distros"]


def _spec(distro: str) -> dict:
    try:
        return _specs()[distro]
    except KeyError:
        raise UnknownDistroError(
            f"{distro!r} is not declared in {FILE_META_DISTROS}. "
            f"Declared: {', '.join(distro_names())}."
        ) from None


def distro_names() -> tuple[str, ...]:
    """Every declared distro id, in declaration order."""
    return tuple(_specs())


def distro_family() -> dict[str, str]:
    """Map each distro id onto the ``os_family`` ansible reports for it."""
    return {name: spec["family"] for name, spec in _specs().items()}


def galaxy_platforms() -> list[dict[str, object]]:
    """Canonical ``galaxy_info.platforms`` block for every role's meta/main.yml.

    Sorted by platform name, which is the order the role files carry and
    which the schema lint compares against verbatim.
    """
    versions = list(_doc()["galaxy_platform_versions"])
    return [
        {"name": name, "versions": list(versions)}
        for name in sorted(spec["galaxy_platform"] for spec in _specs().values())
    ]


def dev_runtime_images() -> tuple[str, ...]:
    """Upstream base images of the development-environment test matrix."""
    return tuple(spec["dev_runtime_image"] for spec in _specs().values())


def dev_runtime_image(distro: str) -> str:
    """Upstream base image the development environment boots a distro from."""
    return _spec(distro)["dev_runtime_image"]


def image_template(kind: str) -> str:
    """Raw reference template, for callers rendering a non-distro slug.

    The shell-side installer scripts loop over distros with their own
    variable, so they render ``{slug}`` themselves rather than per distro.
    """
    return _doc()["images"][kind]


def _render(kind: str, distro: str, **fields: str) -> str:
    return image_template(kind).format(slug=_spec(distro)["slug"], **fields)


def pkgmgr_image(distro: str, owner: str, tag: str) -> str:
    """Reference of the pkgmgr base image a distro's container builds FROM."""
    return _render(IMAGE_PKGMGR, distro, owner=owner, tag=tag)


def pkgmgr_virgin_image(distro: str, owner: str, tag: str) -> str:
    """Reference of the untouched pkgmgr image the install tests boot."""
    return _render(IMAGE_PKGMGR_VIRGIN, distro, owner=owner, tag=tag)


def environment_image(distro: str, owner: str, repository: str, tag: str) -> str:
    """Reference of the environment image built for a distro."""
    return _render(
        IMAGE_ENVIRONMENT, distro, owner=owner, repository=repository, tag=tag
    )
