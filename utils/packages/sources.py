"""One builder per acquisition path.

Each function returns the ordered calls that bring a package in from one
source. :mod:`utils.packages.plan` picks between them; none of them knows
about the others.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from utils.packages.calls import (
    AUR_FETCH,
    EXTERNAL_FETCH,
    STATE_PRESENT,
    ModuleCall,
    package_call,
)

PACMAN_CONF = "/etc/pacman.conf"
AUR_BUILDER_USER = "aur_builder"
AUR_SUDOERS_PATH = "/etc/sudoers.d/11-install-aur_builder"
AUR_BUILD_TOOLCHAIN = ("base-devel", "git", "sudo", "fakeroot")
AUR_MAKEPKG_ARGS = "--skipinteg"
"""The AUR PKGBUILDs this project consumes carry a checksum on a git
source, which makepkg can only reject; integrity rests on the pinned
upstream tag fetched over HTTPS."""

DOWNLOAD_CACHE_DIR = "/var/cache/infinito/packages"
"""Where a pinned vendor artefact is kept: root-owned, so no other local
account can pre-create the path between the checksum check and the
install, and persistent, so a rerun matches the cached file and skips the
transfer."""

DOWNLOAD_CACHE_MODE = "0755"

RPM_GPG_CHECK_DISABLED = True
"""A vendor that runs no repository ships no signing key either, so dnf
would reject every artefact this source installs; the pinned checksum is
what stands in for the signature."""

DEB_CONTROL_TOOL = "xz-utils"
"""Cursor and its kind compress the deb control member with xz, which
``ansible.builtin.apt`` extracts through the ``xz`` binary rather than
through dpkg's own library."""

FLATPAK_PACKAGE = "flatpak"
FLATPAK_METHOD = "system"
FLATPAK_EXPORT_DIR = "/var/lib/flatpak/exports/bin"
FLATPAK_COMMAND_DIR = "/usr/local/bin"
FLATHUB_REMOTE = {
    "name": "flathub",
    "url": "https://dl.flathub.org/repo/flathub.flatpakrepo",
}


def aur_calls(names: list[str]) -> list[ModuleCall]:
    """Prepare the unprivileged build environment, then build through it.

    makepkg refuses to run as root, so the toolchain, a build user and a
    passwordless pacman rule must exist before any AUR package is built.
    """
    return [
        package_call(list(AUR_BUILD_TOOLCHAIN), STATE_PRESENT),
        ModuleCall(
            "ansible.builtin.user", {"name": AUR_BUILDER_USER, "create_home": True}
        ),
        ModuleCall(
            "ansible.builtin.lineinfile",
            {
                "path": AUR_SUDOERS_PATH,
                "line": f"{AUR_BUILDER_USER} ALL=(ALL) NOPASSWD: /usr/bin/pacman",
                "create": True,
                "mode": "0440",
                "validate": "visudo -cf %s",
            },
        ),
        ModuleCall(
            "kewlfft.aur.aur",
            {"use": "makepkg", "name": names, "extra_args": AUR_MAKEPKG_ARGS},
            become_user=AUR_BUILDER_USER,
            retry=AUR_FETCH,
        ),
    ]


def build_calls(build: dict[str, Any]) -> list[ModuleCall]:
    """Install the declared dependencies, then run the build command."""
    return [
        package_call(list(build.get("depends", [])), STATE_PRESENT),
        ModuleCall(
            "ansible.builtin.command",
            {"cmd": build["command"], "creates": build.get("creates")},
            retry=EXTERNAL_FETCH,
        ),
    ]


def download_calls(names: list[str], download: dict[str, Any]) -> list[ModuleCall]:
    """Fetch the pinned vendor artefact, install it, confirm what it gave.

    The cache directory is created first and owned by root, because a
    world-writable one lets another account swap the file between the
    checksum check and the install.

    ``get_url`` compares the checksum before and after the transfer, so a
    file the vendor has replaced fails the task instead of reaching the
    package manager, and a cached file that still matches is not refetched.

    The closing call names the declared packages. They are installed by
    then, so it reaches no repository; it fails loudly when the artefact
    registered under some other name, which would leave ``state: absent``
    with nothing to remove.

    Raises:
        ValueError: the URL names neither a ``.deb`` nor an ``.rpm``, which
            are the only artefacts a local install here can hand over.
    """
    url = str(download["url"])
    artefact = PurePosixPath(urlsplit(url).path)
    dest = f"{DOWNLOAD_CACHE_DIR}/{artefact.name}"

    if artefact.suffix == ".deb":
        prerequisites = [package_call([DEB_CONTROL_TOOL], STATE_PRESENT)]
        install = ModuleCall("ansible.builtin.apt", {"deb": dest})
    elif artefact.suffix == ".rpm":
        prerequisites = []
        install = ModuleCall(
            "ansible.builtin.dnf",
            {
                "name": [dest],
                "state": STATE_PRESENT,
                "disable_gpg_check": RPM_GPG_CHECK_DISABLED,
            },
        )
    else:
        raise ValueError(
            f"download source cannot install a '{artefact.suffix}' artefact; "
            "expected '.deb' or '.rpm'"
        )

    return [
        *prerequisites,
        ModuleCall(
            "ansible.builtin.file",
            {
                "path": DOWNLOAD_CACHE_DIR,
                "state": "directory",
                "owner": "root",
                "group": "root",
                "mode": DOWNLOAD_CACHE_MODE,
            },
        ),
        ModuleCall(
            "ansible.builtin.get_url",
            {
                "url": url,
                "dest": dest,
                "checksum": download["checksum"],
                "mode": "0644",
            },
            retry=EXTERNAL_FETCH,
        ),
        install,
        package_call(names, STATE_PRESENT),
    ]


def flatpak_calls(names: list[str], flatpak: dict[str, Any] | None) -> list[ModuleCall]:
    """Bring up the Flatpak runtime and remote, install the ids, expose them.

    Flatpak exports a launcher named after the application id, so a role
    calling the plain binary name finds nothing on PATH until
    ``flatpak.command`` links it.
    """
    remote = (flatpak or {}).get("remote", FLATHUB_REMOTE)
    calls = [
        package_call([FLATPAK_PACKAGE], STATE_PRESENT),
        ModuleCall(
            "community.general.flatpak_remote",
            {
                "name": remote["name"],
                "flatpakrepo_url": remote["url"],
                "method": FLATPAK_METHOD,
                "state": STATE_PRESENT,
            },
            retry=EXTERNAL_FETCH,
        ),
        ModuleCall(
            "community.general.flatpak",
            {
                "name": names,
                "remote": remote["name"],
                "method": FLATPAK_METHOD,
                "state": STATE_PRESENT,
            },
            retry=EXTERNAL_FETCH,
        ),
    ]

    command = (flatpak or {}).get("command")
    if command:
        calls.append(
            ModuleCall(
                "ansible.builtin.file",
                {
                    "src": f"{FLATPAK_EXPORT_DIR}/{names[0]}",
                    "dest": f"{FLATPAK_COMMAND_DIR}/{command}",
                    "state": "link",
                    "force": True,
                },
            )
        )
    return calls


def pacman_section_calls(section: str, names: list[str]) -> list[ModuleCall]:
    """Uncomment a pacman.conf section, then install through it.

    Arch ships multilib commented out, so the repository holding the 32-bit
    and Steam packages does not exist until the two lines are enabled. The
    regex stops matching once uncommented, which is what makes it idempotent.
    """
    return [
        ModuleCall(
            "ansible.builtin.replace",
            {
                "path": PACMAN_CONF,
                "regexp": rf"^#\s*\[{section}\]\s*\n#\s*Include\s*=\s*(\S+)$",
                "replace": f"[{section}]\\nInclude = \\1",
            },
        ),
        ModuleCall(
            "community.general.pacman",
            {"name": names, "state": STATE_PRESENT, "update_cache": True},
        ),
    ]


def repository_calls(repo: dict[str, Any], names: list[str]) -> list[ModuleCall]:
    """Enable the declared repository, then install through it."""
    if repo.get("managed_externally"):
        return [package_call(names, STATE_PRESENT)]

    if repo.get("pacman_section"):
        return pacman_section_calls(str(repo["pacman_section"]), names)

    if repo.get("copr"):
        return [
            ModuleCall(
                "community.general.copr",
                {"name": repo["copr"], "state": "enabled"},
                retry=EXTERNAL_FETCH,
            ),
            package_call(names, STATE_PRESENT),
        ]

    if repo.get("ppa"):
        return [
            ModuleCall(
                "ansible.builtin.apt_repository",
                {"repo": repo["ppa"], "update_cache": True},
                retry=EXTERNAL_FETCH,
            ),
            package_call(names, STATE_PRESENT),
        ]

    if repo.get("bootstrap_package"):
        return [
            package_call([repo["bootstrap_package"]], STATE_PRESENT),
            package_call(names, STATE_PRESENT),
        ]

    if repo.get("enable_existing"):
        return [
            ModuleCall(
                "ansible.builtin.dnf",
                {
                    "name": names,
                    "state": repo.get("state", STATE_PRESENT),
                    "enablerepo": repo["enable_existing"],
                },
                retry=EXTERNAL_FETCH,
            )
        ]

    return [
        ModuleCall(
            "ansible.builtin.yum_repository",
            {
                "name": repo["name"],
                "description": repo["description"],
                "baseurl": repo["baseurl"],
                "gpgkey": repo["gpgkey"],
                "gpgcheck": repo.get("gpgcheck", True),
            },
        ),
        package_call(names, STATE_PRESENT),
    ]
