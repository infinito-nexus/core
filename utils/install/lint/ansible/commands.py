"""Install ansible-playbook and ansible-galaxy via system package manager."""

from __future__ import annotations

from utils.install.primitives import log, which
from utils.install.system_pkg import install_command_via_pkg


def ensure() -> None:
    for command in ("ansible-playbook", "ansible-galaxy"):
        if which(command):
            continue
        log(f"Missing command '{command}'. Attempting system package installation.")
        install_command_via_pkg(command)
        if not which(command):
            raise RuntimeError(
                f"Command '{command}' is still unavailable after installation."
            )
