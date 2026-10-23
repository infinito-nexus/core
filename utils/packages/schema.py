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
          bootstrap_package: centos-release-nfs-ganesha11
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

``source: flatpak`` takes application ids rather than package names and
pulls them from a Flatpak remote::

    blender:
      centos:
        source: flatpak
        names: [org.blender.Blender]
        flatpak:
          command: blender

``flatpak.command`` is the name the role invokes. Flatpak exports a launcher
named after the application id, not after the binary inside it, so without
this key a role calling ``blender`` finds nothing on PATH.

``source: download`` fetches one vendor artefact and installs it locally,
for a vendor that publishes a ``.deb`` or ``.rpm`` but runs no repository::

    cursor:
      Debian:
        source: download
        names: [cursor]
        download:
          url: https://downloads.cursor.com/.../cursor_3.27.6_amd64.deb
          checksum: sha256:cf5f44...

``names`` is what the artefact installs as, so removal still goes through
the package manager. ``checksum`` is mandatory: the URL alone would install
whatever the vendor serves today, and a mismatch must abort the fetch
rather than reach the package manager.

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

from utils.distros import distro_family

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
SOURCE_DOWNLOAD = "download"
SOURCE_FLATPAK = "flatpak"
SOURCES: tuple[str, ...] = (
    SOURCE_REPO,
    SOURCE_AUR,
    SOURCE_COPR,
    SOURCE_PPA,
    SOURCE_BUILD,
    SOURCE_DOWNLOAD,
    SOURCE_FLATPAK,
)
"""How the names are acquired. ``repo`` is the distribution's own package
manager; ``aur``, ``copr`` and ``ppa`` are the community managers Arch,
Fedora and Ubuntu ship alongside it; ``build`` compiles from source where
no manager carries the package at all; ``download`` installs a checksum-
pinned vendor artefact where the vendor publishes a package file but no
repository; ``flatpak`` installs an application id from a Flatpak remote,
which is the only upstream channel for much of the desktop set on EL."""

DOWNLOAD_CHECKSUM_PREFIXES: tuple[str, ...] = ("sha256:", "sha512:")
"""Digest algorithms strong enough to pin a vendor artefact. ``get_url``
also accepts md5 and sha1, which a prefix check must keep out."""

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

DISTRO_FAMILY: dict[str, str] = distro_family()
"""The default distro matrix mapped onto the ``os_family`` ansible reports
for it, read from the ``meta/distros.yml`` SPOT. Coverage is required for
every key."""


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
    flatpak: dict[str, Any] | None = None
    download: dict[str, Any] | None = None


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


def _validate_download(
    package_id: str, key: str, source: str, download: Any, path: Path
) -> None:
    if download is None:
        if source == SOURCE_DOWNLOAD:
            raise PackagesShapeError(
                f"{path}: {package_id}.{key} declares source "
                f"'{SOURCE_DOWNLOAD}' but no download block."
            )
        return
    if source != SOURCE_DOWNLOAD:
        raise PackagesShapeError(
            f"{path}: {package_id}.{key} declares a download block without "
            f"source '{SOURCE_DOWNLOAD}'."
        )
    if not isinstance(download, dict):
        raise PackagesShapeError(
            f"{path}: {package_id}.{key}.download must be a mapping, "
            f"got {type(download).__name__}."
        )
    url = download.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise PackagesShapeError(
            f"{path}: {package_id}.{key}.download.url must be an https URL."
        )
    checksum = download.get("checksum")
    if not isinstance(checksum, str) or not checksum.startswith(
        DOWNLOAD_CHECKSUM_PREFIXES
    ):
        raise PackagesShapeError(
            f"{path}: {package_id}.{key}.download.checksum must be one of "
            f"{sorted(DOWNLOAD_CHECKSUM_PREFIXES)} followed by the digest; "
            "without it the URL installs whatever the vendor serves today."
        )


def _validate_flatpak(
    package_id: str, key: str, source: str, flatpak: Any, path: Path
) -> None:
    if flatpak is None:
        return
    if source != SOURCE_FLATPAK:
        raise PackagesShapeError(
            f"{path}: {package_id}.{key} declares a flatpak block without "
            f"source '{SOURCE_FLATPAK}'."
        )
    if not isinstance(flatpak, dict):
        raise PackagesShapeError(
            f"{path}: {package_id}.{key}.flatpak must be a mapping, "
            f"got {type(flatpak).__name__}."
        )
    command = flatpak.get("command")
    if command is not None and not isinstance(command, str):
        raise PackagesShapeError(
            f"{path}: {package_id}.{key}.flatpak.command must be a string."
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

    download = value.get("download")
    _validate_download(package_id, key, source, download, path)

    flatpak = value.get("flatpak")
    _validate_flatpak(package_id, key, source, flatpak, path)

    return PackageSpec(
        tuple(names), str(source), repo, virtual, build, flatpak, download
    )
