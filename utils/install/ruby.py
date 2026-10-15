"""Ruby runtime provisioning for the Ruby unit suite."""

from __future__ import annotations

import subprocess

from utils.install.primitives import log
from utils.install.system_pkg import (
    detect_package_manager,
    ensure_command_present,
    install_package_candidates,
)

_MINITEST_PACKAGES: dict[str, list[str]] = {
    "pacman": ["ruby-minitest"],
    "dnf": ["rubygem-minitest"],
    "yum": ["rubygem-minitest"],
    "apt-get": ["ruby-minitest"],
}


def minitest_loadable() -> bool:
    """Return whether the installed ruby can require minitest.

    Returns:
        ``True`` when ``ruby -e 'require "minitest"'`` exits 0.
    """
    probe = subprocess.run(
        ["ruby", "-e", 'require "minitest"'], capture_output=True, check=False
    )
    return probe.returncode == 0


def ensure_minitest_present() -> None:
    """Make minitest loadable, installing its package if ruby lacks it.

    Raises:
        RuntimeError: no package mapping for the detected package manager, or
            minitest is still not loadable after the install.
    """
    if minitest_loadable():
        return

    manager = detect_package_manager()
    packages = _MINITEST_PACKAGES.get(manager)
    if packages is None:
        raise RuntimeError(f"No installer mapping defined for minitest on '{manager}'.")

    log(f"Ruby cannot load minitest. Attempting installation via {manager}.")
    install_package_candidates(manager, packages)

    if not minitest_loadable():
        raise RuntimeError(
            f"minitest still not loadable after installing {packages} via {manager}"
        )


def ensure_ruby_present() -> None:
    """Install the Ruby interpreter and minitest through the system package manager.

    Raises:
        RuntimeError: ruby or minitest is still absent after the install attempt.
    """
    ensure_command_present("ruby")
    ensure_minitest_present()


if __name__ == "__main__":
    ensure_ruby_present()
