from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from utils.distros import distro_family
from utils.env.parser import custom_env_value, parse_static_env

if TYPE_CHECKING:
    from utils.env.context import BuildContext, EnvBuilder

KEY = "INFINITO_DISTRO"
COMMENT = "Distro the stack deploys: an explicit value, else an Arch, Debian or Ubuntu host's own, else the default.env fallback."
HOST_FAMILIES = frozenset({"Archlinux", "Debian"})
OS_RELEASE = Path("/etc/os-release")


def host_distro(os_release: Path) -> str:
    """
    Args:
        os_release: the host's os-release file.

    Returns:
        The host's ``ID`` when it is a declared distro of a pacman or apt
        family, empty for every other host and for a missing file.
    """
    if not os_release.is_file():
        return ""
    host = parse_static_env(os_release).get("ID", "").strip().lower()
    return host if distro_family().get(host) in HOST_FAMILIES else ""


def explicit_distro(repo_root: Path) -> str:
    """
    Args:
        repo_root: the checkout whose ``custom.env`` is read.

    Returns:
        The value ``custom.env`` sets, else the exported one, else empty.
    """
    return custom_env_value(repo_root, KEY) or os.environ.get(KEY, "").strip()


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    derived = "" if (ctx.on_gha or ctx.on_act) else host_distro(OS_RELEASE)
    eb.set(
        KEY,
        explicit_distro(ctx.repo_root) or derived or ctx.static.get(KEY, ""),
        comment=COMMENT,
    )
