"""Install shellcheck via system package manager."""

from __future__ import annotations

from utils.install.primitives import log, which
from utils.install.system_pkg import install_command_via_pkg


def ensure() -> None:
    if which("shellcheck"):
        return

    log("Missing command 'shellcheck'. Attempting system package installation.")
    install_command_via_pkg("shellcheck")

    if not which("shellcheck"):
        raise RuntimeError(
            "Command 'shellcheck' is still unavailable after installation."
        )
