"""INFINITO_CACHE_HOST_PACMAN_PATH: the pacman cache of an Arch Linux host, for an arch stack to read at the same path."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from utils.distros import distro_family
from utils.env.parser import parse_static_env
from utils.env.runtime import run_helper

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_HOST_PACMAN_PATH"
COMMENT = "Pacman cache of an Arch Linux host an arch stack mounts read-only at the same path; empty on every other host or stack."
PACMAN_FAMILY = "Archlinux"
ARCH_HOST_ID = "arch"
OS_RELEASE = Path("/etc/os-release")


def host_id(os_release: Path) -> str:
    """Return the ``ID`` an os-release file declares.

    Args:
        os_release: the host's os-release file.

    Returns:
        The lowercased id, empty when the file is missing or declares none.
    """
    if not os_release.is_file():
        return ""
    return parse_static_env(os_release).get("ID", "").strip().lower()


def host_cache(repo_root: Path) -> str:
    """Return the first ``CacheDir`` the host's ``pacman-conf`` reports.

    Args:
        repo_root: working directory for the ``pacman-conf`` call.

    Returns:
        The directory without its trailing slash, empty when the host has no
        ``pacman-conf`` or the directory does not exist.
    """
    dirs = run_helper(["pacman-conf", "CacheDir"], repo_root).splitlines()
    first = dirs[0].strip().rstrip("/") if dirs else ""
    return first if first and Path(first).is_dir() else ""


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    pacman_stack = distro_family().get(eb.get("INFINITO_DISTRO")) == PACMAN_FAMILY
    arch_host = host_id(OS_RELEASE) == ARCH_HOST_ID
    eb.setdefault(
        KEY,
        host_cache(ctx.repo_root) if pacman_stack and arch_host else "",
        comment=COMMENT,
    )
