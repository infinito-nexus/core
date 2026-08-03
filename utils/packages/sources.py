"""One builder per acquisition path.

Each function returns the ordered calls that bring a package in from one
source. :mod:`utils.packages.plan` picks between them; none of them knows
about the others.
"""

from __future__ import annotations

from typing import Any

from utils.packages.calls import (
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
            retry=EXTERNAL_FETCH,
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
