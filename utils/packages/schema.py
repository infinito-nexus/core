"""Declaration shape for ``meta/packages.yml``.

Owns what a package entry may say and how one distro entry becomes a
concrete :class:`PackageSpec`. Finding and indexing the declarations is
:mod:`utils.packages.registry`; turning a spec into module calls is
:mod:`utils.packages.plan`.

The same shape serves the repository-root file, which holds the shared
collection any role and any inventory bundle may install from, and a
role's own file, which holds what only that role installs.

The file is a mapping of logical package id to a distro mapping. Keys are
``ansible_facts['os_family']`` values; a lowercase distribution name
(``ubuntu``, ``centos``, ``fedora``, ``arch``, ``debian``) overrides its
family when that one distribution differs::

    nfs-ganesha:
      Debian: [nfs-ganesha, nfs-ganesha-vfs]
      RedHat: [nfs-ganesha, nfs-ganesha-vfs]
      centos:
        names: [nfs-ganesha, nfs-ganesha-vfs]
        repo:
          name: centos-nfs-ganesha11
          description: CentOS Storage SIG nfs-ganesha 11
          baseurl: https://mirror.stream.centos.org/SIGs/$releasever-stream/storage/$basearch/nfsganesha-11/
          gpgkey: https://www.centos.org/keys/RPM-GPG-KEY-CentOS-SIG-Storage
      Archlinux:
        source: aur
        names: [nfs-ganesha]

``repo`` carries the repository the names come from, defined inline on the
entry that needs it: a full definition (``name``/``description``/
``baseurl``/``gpgkey``) rendered as a yum repo, ``bootstrap_package`` for a
repo shipped as a package such as ``epel-release``, ``enable_existing`` to
switch on a repo the distro already ships, ``pacman_section`` to uncomment
a section of ``pacman.conf`` such as ``multilib``, ``copr``/``ppa`` for a
community repository, or ``managed_externally`` when the role sets it up
itself.

A bare list is shorthand for ``{names: [...], source: repo}``. An empty
list states that the package is deliberately not installed on that family,
which counts as covered; a *missing* key is a coverage gap.

``virtual: true`` records that the package manager satisfies the name
through an RPM ``Provides`` rather than a package of that name, so an index
lookup by name legitimately finds nothing while the install works.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

ROLE_FILE_META_PACKAGES = "meta/packages.yml"
INVENTORY_PACKAGES_VAR = "PACKAGES"
"""Inventory variable listing extra package ids a bundle installs."""

SOURCE_REPO = "repo"
SOURCE_AUR = "aur"
SOURCE_COPR = "copr"
SOURCE_PPA = "ppa"
SOURCE_BUILD = "build"
SOURCES: tuple[str, ...] = (
    SOURCE_REPO,
    SOURCE_AUR,
    SOURCE_COPR,
    SOURCE_PPA,
    SOURCE_BUILD,
)
"""How the names are acquired. ``repo`` is the distribution's own package
manager; ``aur``, ``copr`` and ``ppa`` are the community managers Arch,
Fedora and Ubuntu ship alongside it; ``build`` compiles from source where
no manager carries the package at all."""

REPO_KEYS: frozenset[str] = frozenset(
    {
        "baseurl",
        "bootstrap_package",
        "enable_existing",
        "managed_externally",
        "pacman_section",
        "copr",
        "ppa",
    }
)
"""A repository definition must declare at least one of these; the rest
(``name``, ``description``, ``gpgkey``, ``gpgcheck``, ``state``) qualify it."""

DISTRO_FAMILY: dict[str, str] = {
    "arch": "Archlinux",
    "debian": "Debian",
    "ubuntu": "Debian",
    "fedora": "RedHat",
    "centos": "RedHat",
}
"""The default distro matrix mapped onto the ``os_family`` ansible reports
for it. Coverage is required for every key."""


class PackagesShapeError(ValueError):
    """Raised when a ``meta/packages.yml`` violates the declared shape."""


@dataclass(frozen=True)
class PackageSpec:
    """Resolved install instruction for one package on one distribution."""

    names: tuple[str, ...]
    source: str = SOURCE_REPO
    repo: dict[str, Any] | None = None
    virtual: bool = False
    build: dict[str, Any] | None = None


def _validate_repo(package_id: str, key: str, repo: Any, path: Path) -> None:
    if not isinstance(repo, dict):
        raise PackagesShapeError(
            f"{path}: {package_id}.{key}.repo must be an inline repository "
            f"definition (mapping), got {type(repo).__name__}."
        )
    if not repo.keys() & REPO_KEYS:
        raise PackagesShapeError(
            f"{path}: {package_id}.{key}.repo declares none of {sorted(REPO_KEYS)}."
        )


def _validate_build(
    package_id: str, key: str, source: str, build: Any, path: Path
) -> None:
    if source == SOURCE_BUILD and not isinstance(build, dict):
        raise PackagesShapeError(
            f"{path}: {package_id}.{key} declares source 'build' but no build block."
        )
    if isinstance(build, dict) and not build.get("command"):
        raise PackagesShapeError(
            f"{path}: {package_id}.{key}.build must declare a 'command'."
        )


def normalize_entry(package_id: str, key: str, value: Any, path: Path) -> PackageSpec:
    """Turn a bare list or a spec mapping into a :class:`PackageSpec`."""
    if isinstance(value, list):
        value = {"names": value}
    if not isinstance(value, dict):
        raise PackagesShapeError(
            f"{path}: {package_id}.{key} must be a list of names or a mapping, "
            f"got {type(value).__name__}."
        )

    names = value.get("names")
    if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
        raise PackagesShapeError(
            f"{path}: {package_id}.{key}.names must be a list of strings."
        )

    source = value.get("source", SOURCE_REPO)
    if source not in SOURCES:
        raise PackagesShapeError(
            f"{path}: {package_id}.{key}.source {source!r} is not one of {SOURCES}."
        )

    repo = value.get("repo")
    if repo is not None:
        _validate_repo(package_id, key, repo, path)

    virtual = value.get("virtual", False)
    if not isinstance(virtual, bool):
        raise PackagesShapeError(
            f"{path}: {package_id}.{key}.virtual must be a boolean when set."
        )

    build = value.get("build")
    _validate_build(package_id, key, source, build, path)

    return PackageSpec(tuple(names), str(source), repo, virtual, build)
