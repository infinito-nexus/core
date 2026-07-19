"""System-package-manager dispatch (pacman / apt-get / dnf / yum / brew)."""

from __future__ import annotations

import contextlib
import shutil
import subprocess

from utils.install.primitives import log, run_privileged, warn

_SUPPORTED = ("pacman", "apt-get", "dnf", "yum", "brew")


def detect_package_manager() -> str:
    for manager in _SUPPORTED:
        if shutil.which(manager) is not None:
            return manager
    raise RuntimeError("No supported package manager found")


def _prepare_manager(manager: str) -> None:
    if manager == "apt-get":
        run_privileged(["apt-get", "-o", "DPkg::Lock::Timeout=600", "update"])
    elif manager == "dnf":
        with contextlib.suppress(subprocess.CalledProcessError):
            run_privileged(["dnf", "-y", "install", "dnf-plugins-core"])
        with contextlib.suppress(subprocess.CalledProcessError):
            run_privileged(["dnf", "-y", "install", "epel-release"])
    elif manager == "yum":
        with contextlib.suppress(subprocess.CalledProcessError):
            run_privileged(["yum", "-y", "install", "yum-utils"])
        with contextlib.suppress(subprocess.CalledProcessError):
            run_privileged(["yum", "-y", "install", "epel-release"])


def _install_one(manager: str, package: str) -> bool:
    log(f"Installing package '{package}' via {manager}")
    try:
        if manager == "pacman":
            run_privileged(["pacman", "-Syu", "--noconfirm", "--needed", package])
        elif manager == "apt-get":
            run_privileged(
                [
                    "apt-get",
                    "-o",
                    "DPkg::Lock::Timeout=600",
                    "install",
                    "-y",
                    "--no-install-recommends",
                    package,
                ]
            )
        elif manager == "dnf":
            run_privileged(["dnf", "-y", "install", package])
        elif manager == "yum":
            run_privileged(["yum", "-y", "install", package])
        elif manager == "brew":
            subprocess.run(["brew", "install", package], check=True)
        else:
            warn(f"Unsupported package manager: {manager}")
            return False
    except subprocess.CalledProcessError:
        return False
    return True


def install_package_candidates(manager: str, packages: list[str]) -> None:
    _prepare_manager(manager)
    for package in packages:
        if _install_one(manager, package):
            return
    raise RuntimeError(f"All package candidates failed via {manager}: {packages}")


_COMMAND_PACKAGES: dict[str, dict[str, list[str]]] = {
    "ansible-playbook": {
        "pacman": ["ansible-core", "ansible"],
        "apt-get": ["ansible-core", "ansible"],
        "dnf": ["ansible-core", "ansible"],
        "yum": ["ansible-core", "ansible"],
        "brew": ["ansible"],
    },
    "ansible-galaxy": {
        "pacman": ["ansible-core", "ansible"],
        "apt-get": ["ansible-core", "ansible"],
        "dnf": ["ansible-core", "ansible"],
        "yum": ["ansible-core", "ansible"],
        "brew": ["ansible"],
    },
    "ruff": {m: ["ruff"] for m in _SUPPORTED},
    "shfmt": {m: ["shfmt"] for m in _SUPPORTED},
    "shellcheck": {m: ["shellcheck"] for m in _SUPPORTED},
    "unzip": {m: ["unzip"] for m in _SUPPORTED},
    "npm": {
        "pacman": ["npm", "nodejs"],
        "apt-get": ["npm", "nodejs"],
        "dnf": ["npm", "nodejs"],
        "yum": ["npm", "nodejs"],
        "brew": ["node"],
    },
}


def install_command_via_pkg(command_name: str) -> None:
    manager = detect_package_manager()
    mapping = _COMMAND_PACKAGES.get(command_name)
    if mapping is None or manager not in mapping:
        raise RuntimeError(
            f"No installer mapping defined for '{command_name}' on '{manager}'."
        )

    log(f"Missing command '{command_name}'. Attempting installation via {manager}.")
    install_package_candidates(manager, mapping[manager])


__all__ = [
    "detect_package_manager",
    "install_command_via_pkg",
    "install_package_candidates",
]
