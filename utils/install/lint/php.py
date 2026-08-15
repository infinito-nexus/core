"""Install the PHP interpreter, whose syntax check is the lint."""

from __future__ import annotations

from utils.install.primitives import log, which
from utils.install.system_pkg import install_command_via_pkg


def ensure() -> None:
    if which("php"):
        return

    log("Missing command 'php'. Attempting system package installation.")
    install_command_via_pkg("php")

    if not which("php"):
        raise RuntimeError("Command 'php' is still unavailable after installation.")
