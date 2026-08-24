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
        run_privileged(
            [
                "apt-get",
                "-o",
                "DPkg::Lock::Timeout=600",
                "-o",
                "Acquire::Retries=3",
                "update",
            ]
        )
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
                    "-o",
                    "Acquire::Retries=3",
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


def install_package_candidates(
    manager: str, packages: list[str], provides: str | None = None
) -> None:
    """Install packages until ``provides`` is callable, or all candidates fail.

    Args:
        manager: the detected package manager.
        packages: candidate package names, most specific first.
        provides: the command the caller needs.
    """
    _prepare_manager(manager)
    installed_any = False
    for package in packages:
        if _install_one(manager, package):
            installed_any = True
            if provides is None or shutil.which(provides) is not None:
                return
    if installed_any and provides is not None:
        raise RuntimeError(
            f"Installed {packages} via {manager} but {provides!r} is still not on "
            f"PATH; the candidate list does not cover this distribution."
        )
    if not installed_any:
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
    "php": {
        "pacman": ["php"],
        "apt-get": ["php-cli"],
        "dnf": ["php-cli"],
        "yum": ["php-cli"],
        "brew": ["php"],
    },
    "ruby": {m: ["ruby"] for m in _SUPPORTED},
    "ruff": {m: ["ruff"] for m in _SUPPORTED},
    "shfmt": {m: ["shfmt"] for m in _SUPPORTED},
    "shellcheck": {m: ["shellcheck"] for m in _SUPPORTED},
    "unzip": {m: ["unzip"] for m in _SUPPORTED},
    "php": {
        "pacman": ["php"],
        "apt-get": ["php-cli", "php"],
        "dnf": ["php-cli", "php"],
        "yum": ["php-cli", "php"],
        "brew": ["php"],
    },
    "ruby": {m: ["ruby"] for m in _SUPPORTED},
    "composer": {m: ["composer"] for m in _SUPPORTED},
    "npm": {
        "pacman": ["npm", "nodejs"],
        "apt-get": ["npm", "nodejs"],
        "dnf": ["npm", "nodejs"],
        "yum": ["npm", "nodejs"],
        "brew": ["node"],
    },
    "node": {
        "pacman": ["nodejs"],
        "apt-get": ["nodejs"],
        "dnf": ["nodejs"],
        "yum": ["nodejs"],
        "brew": ["node"],
    },
}


_PHP_EXTENSION_PACKAGES: dict[str, dict[str, list[str]]] = {
    "dom": {
        "pacman": ["php"],
        "apt-get": ["php-xml"],
        "dnf": ["php-xml"],
        "yum": ["php-xml"],
        "brew": ["php"],
    },
    "mbstring": {
        "pacman": ["php"],
        "apt-get": ["php-mbstring"],
        "dnf": ["php-mbstring"],
        "yum": ["php-mbstring"],
        "brew": ["php"],
    },
    "xmlwriter": {
        "pacman": ["php"],
        "apt-get": ["php-xml"],
        "dnf": ["php-xml"],
        "yum": ["php-xml"],
        "brew": ["php"],
    },
}


def loaded_php_extensions() -> set[str]:
    """Return the extensions the php CLI currently loads, lower-cased.

    Returns:
        the set reported by ``php -m``, empty when php cannot be queried.
    """
    result = subprocess.run(["php", "-m"], capture_output=True, text=True, check=False)
    return {line.strip().lower() for line in result.stdout.splitlines() if line.strip()}


def ensure_php_extension_present(extension: str) -> None:
    """Make a PHP extension available, installing its package if absent.

    A distro ships the interpreter and its extensions as separate packages, so
    a present ``php`` binary says nothing about them and ``ensure_command_present``
    returns early on one. The extension is therefore probed against ``php -m``.

    Args:
        extension: extension name as ``php -m`` reports it.

    Raises:
        RuntimeError: no mapping for this extension on the detected package
            manager, or the extension is still absent after the install.
    """
    if extension in loaded_php_extensions():
        return

    manager = detect_package_manager()
    mapping = _PHP_EXTENSION_PACKAGES.get(extension)
    if mapping is None or manager not in mapping:
        raise RuntimeError(
            f"No installer mapping defined for PHP extension "
            f"'{extension}' on '{manager}'."
        )

    log(f"Missing PHP extension '{extension}'. Attempting installation via {manager}.")
    install_package_candidates(manager, mapping[manager])

    if extension not in loaded_php_extensions():
        raise RuntimeError(
            f"PHP extension '{extension}' still absent after installing "
            f"{mapping[manager]} via {manager}"
        )


def ensure_command_present(command_name: str) -> None:
    """Make a command available, installing it if the host lacks it.

    Args:
        command_name: executable name, must be a key of the installer mapping.

    Raises:
        RuntimeError: the command is still absent after the install attempt.
    """
    if shutil.which(command_name) is not None:
        return

    install_command_via_pkg(command_name)

    if shutil.which(command_name) is None:
        raise RuntimeError(f"{command_name} not found and could not be installed")


def install_command_via_pkg(command_name: str) -> None:
    manager = detect_package_manager()
    mapping = _COMMAND_PACKAGES.get(command_name)
    if mapping is None or manager not in mapping:
        raise RuntimeError(
            f"No installer mapping defined for '{command_name}' on '{manager}'."
        )

    log(f"Missing command '{command_name}'. Attempting installation via {manager}.")
    install_package_candidates(manager, mapping[manager], provides=command_name)


__all__ = [
    "detect_package_manager",
    "ensure_command_present",
    "ensure_php_extension_present",
    "install_command_via_pkg",
    "install_package_candidates",
    "loaded_php_extensions",
]
