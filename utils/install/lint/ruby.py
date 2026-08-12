"""Install the Ruby interpreter, whose syntax check is the lint."""

from __future__ import annotations

from utils.install.primitives import log, which
from utils.install.system_pkg import install_command_via_pkg


def ensure() -> None:
    if which("ruby"):
        return

    log("Missing command 'ruby'. Attempting system package installation.")
    install_command_via_pkg("ruby")

    if not which("ruby"):
        raise RuntimeError("Command 'ruby' is still unavailable after installation.")
