"""Install plans for the package registry.

Turns a resolved :class:`~utils.packages.registry.PackageSpec` into the
ordered module calls that acquire it. Keeping this pure means every
acquisition path - distribution repository, AUR, COPR, PPA, source build -
is unit-testable without an Ansible connection; the action plugin only
executes what it is handed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils.packages.schema import (
    SOURCE_AUR,
    SOURCE_BUILD,
    SOURCE_COPR,
    SOURCE_PPA,
    PackageSpec,
)

STATE_PRESENT = "present"
STATE_ABSENT = "absent"
STATES: tuple[str, ...] = (STATE_PRESENT, STATE_ABSENT)

PACMAN_CONF = "/etc/pacman.conf"
AUR_BUILDER_USER = "aur_builder"
AUR_SUDOERS_PATH = "/etc/sudoers.d/11-install-aur_builder"
AUR_BUILD_TOOLCHAIN = ("base-devel", "git", "sudo", "fakeroot")
AUR_MAKEPKG_ARGS = "--skipinteg"
"""The AUR PKGBUILDs this project consumes carry a checksum on a git
source, which makepkg can only reject; integrity rests on the pinned
upstream tag fetched over HTTPS."""


@dataclass(frozen=True)
class ModuleCall:
    """One Ansible module invocation the action plugin should execute."""

    module: str
    args: dict[str, Any] = field(default_factory=dict)
    become_user: str | None = None


def _package(names: list[str], state: str) -> ModuleCall:
    return ModuleCall("ansible.builtin.package", {"name": names, "state": state})


def _aur_bootstrap() -> list[ModuleCall]:
    """Prepare the unprivileged build environment makepkg requires.

    makepkg refuses to run as root, so the toolchain, a build user and a
    passwordless pacman rule must exist before any AUR package is built.
    """
    return [
        _package(list(AUR_BUILD_TOOLCHAIN), STATE_PRESENT),
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
    ]


def _pacman_section_calls(section: str, names: list[str]) -> list[ModuleCall]:
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


def _repository_calls(repo: dict[str, Any], names: list[str]) -> list[ModuleCall]:
    if repo.get("managed_externally"):
        return [_package(names, STATE_PRESENT)]

    if repo.get("pacman_section"):
        return _pacman_section_calls(str(repo["pacman_section"]), names)

    if repo.get("copr"):
        return [
            ModuleCall(
                "community.general.copr", {"name": repo["copr"], "state": "enabled"}
            ),
            _package(names, STATE_PRESENT),
        ]

    if repo.get("ppa"):
        return [
            ModuleCall(
                "ansible.builtin.apt_repository",
                {"repo": repo["ppa"], "update_cache": True},
            ),
            _package(names, STATE_PRESENT),
        ]

    if repo.get("bootstrap_package"):
        return [
            _package([repo["bootstrap_package"]], STATE_PRESENT),
            _package(names, STATE_PRESENT),
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
        _package(names, STATE_PRESENT),
    ]


def build_plan(spec: PackageSpec, state: str) -> list[ModuleCall]:
    """Return the ordered module calls that bring ``spec`` into ``state``."""
    names = list(spec.names)
    if not names:
        return []

    if state == STATE_ABSENT:
        return [_package(names, STATE_ABSENT)]

    if spec.source == SOURCE_AUR:
        return [
            *_aur_bootstrap(),
            ModuleCall(
                "kewlfft.aur.aur",
                {"use": "makepkg", "name": names, "extra_args": AUR_MAKEPKG_ARGS},
                become_user=AUR_BUILDER_USER,
            ),
        ]

    if spec.source == SOURCE_BUILD:
        if not spec.build:
            raise ValueError("source 'build' requires a 'build' block")
        return [
            _package(list(spec.build.get("depends", [])), STATE_PRESENT),
            ModuleCall(
                "ansible.builtin.command",
                {"cmd": spec.build["command"], "creates": spec.build.get("creates")},
            ),
        ]

    if spec.source in (SOURCE_COPR, SOURCE_PPA) and not spec.repo:
        raise ValueError(f"source '{spec.source}' requires a 'repo' block")

    if spec.repo:
        return _repository_calls(spec.repo, names)
    return [_package(names, STATE_PRESENT)]
