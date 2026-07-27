"""Package registry SPOT.

Every installable package is declared exactly once, in one of two places:

* the repository-root ``meta/packages.yml`` holds the shared collection -
  packages more than one role or an inventory bundle installs;
* a role's ``roles/<role>/meta/packages.yml`` holds what only that role
  installs.

This module finds those declarations, indexes them by id and resolves one
for a target distribution. The declaration shape itself lives in
:mod:`utils.packages.schema`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.packages.schema import (
    DISTRO_FAMILY,
    INVENTORY_PACKAGES_VAR,
    ROLE_FILE_META_PACKAGES,
    PackageSpec,
    PackagesShapeError,
    normalize_entry,
)


@dataclass(frozen=True)
class Declaration:
    """One package id, declared either repository-wide or by one role."""

    package_id: str
    role: str | None
    path: Path
    mapping: dict[str, Any] = field(repr=False)

    @property
    def shared(self) -> bool:
        """Whether any role may install this id."""
        return self.role is None

    @property
    def owner(self) -> str:
        """Human-readable owner for lint and runtime messages."""
        return self.role or "the shared registry"


def iter_package_files(project_root: Path) -> Iterator[tuple[str | None, Path]]:
    """Yield ``(role_or_None, path)`` for every package declaration file.

    The shared root file comes first and carries ``None`` as its role.
    """
    root = Path(project_root)
    shared = root / ROLE_FILE_META_PACKAGES
    if shared.is_file():
        yield None, shared

    roles = root / "roles"
    if not roles.is_dir():
        return
    for role_dir in sorted(roles.iterdir()):
        path = role_dir / ROLE_FILE_META_PACKAGES
        if role_dir.is_dir() and path.is_file():
            yield role_dir.name, path


def load_declarations(project_root: Path) -> list[Declaration]:
    """Read every ``meta/packages.yml`` without deduplicating.

    Duplicates are returned as-is so the uniqueness lint can report all
    offenders instead of failing on the first one.
    """
    declarations: list[Declaration] = []
    for role, path in iter_package_files(project_root):
        raw = load_yaml_any(str(path), default_if_missing={}) or {}
        if not isinstance(raw, dict):
            raise PackagesShapeError(
                f"{path}: expected a mapping of package id to distro mapping, "
                f"got {type(raw).__name__}."
            )
        for package_id, mapping in raw.items():
            if not isinstance(mapping, dict):
                raise PackagesShapeError(
                    f"{path}: package '{package_id}' must map distro keys to "
                    f"specs, got {type(mapping).__name__}."
                )
            declarations.append(Declaration(str(package_id), role, path, mapping))
    return declarations


def iter_inventory_package_lists(
    project_root: Path,
) -> Iterator[tuple[Path, list[str]]]:
    """Yield ``(path, ids)`` for every inventory that defines ``PACKAGES``."""
    inventories = Path(project_root) / "inventories"
    if not inventories.is_dir():
        return
    for path in sorted(inventories.rglob("*.yml")):
        raw = load_yaml_any(str(path), default_if_missing={}) or {}
        packages = (raw.get("all") or {}).get("vars", {}).get(INVENTORY_PACKAGES_VAR)
        if packages is None:
            continue
        if not isinstance(packages, list) or any(
            not isinstance(item, str) for item in packages
        ):
            raise PackagesShapeError(
                f"{path}: {INVENTORY_PACKAGES_VAR} must be a list of package ids."
            )
        yield path, packages


def resolve(
    declaration: Declaration, distro: str, family: str | None = None
) -> PackageSpec | None:
    """Resolve ``distro`` through its distro override, else its os_family.

    ``family`` is the ``os_family`` ansible reports for the host. Callers
    that have facts (the action plugin) pass it, so distributions outside
    the CI matrix - Manjaro, Mint, Rocky - still resolve through their
    family. Callers without facts (lints, the availability test) omit it
    and the family is derived from :data:`DISTRO_FAMILY`, which only
    covers the default matrix.

    Returns ``None`` when neither key is declared, which is what the
    coverage lint reports as a gap.
    """
    distro = distro.strip().lower()
    if family is None:
        family = DISTRO_FAMILY.get(distro)
    if not family:
        raise PackagesShapeError(
            f"Unknown distribution {distro!r} and no os_family given; the "
            f"default matrix is {sorted(DISTRO_FAMILY)}."
        )
    for key in (distro, family):
        if key in declaration.mapping:
            return normalize_entry(
                declaration.package_id, key, declaration.mapping[key], declaration.path
            )
    return None


def build_registry(project_root: Path) -> dict[str, Declaration]:
    """Index every declaration by package id.

    Raises on a duplicate id: two files declaring the same package is the
    missing-SPOT condition the uniqueness lint exists to prevent, so the
    runtime resolver must never silently pick one.
    """
    registry: dict[str, Declaration] = {}
    for declaration in load_declarations(project_root):
        previous = registry.get(declaration.package_id)
        if previous is not None:
            raise PackagesShapeError(
                f"Package '{declaration.package_id}' is declared twice: "
                f"{previous.path} and {declaration.path}. Declare it once, in "
                f"the root {ROLE_FILE_META_PACKAGES} when more than one role "
                f"needs it."
            )
        registry[declaration.package_id] = declaration
    return registry


def project_root_from_env() -> Path:
    """Repository root, overridable for tests via ``INFINITO_PROJECT_ROOT``."""
    key = "INFINITO_PROJECT_ROOT"  # nocheck: test-only override, never set by a deploy
    override = os.environ.get(key)
    if override:
        return Path(override)
    return Path(str(PROJECT_ROOT))
