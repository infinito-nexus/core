"""Install ruff: system-pkg first, pip fallback."""

from __future__ import annotations

import os

from utils.install.pip import install_pip_pkg
from utils.install.primitives import log, which
from utils.install.system_pkg import detect_package_manager, install_command_via_pkg


def ensure() -> None:
    if which("ruff"):
        return

    log("Missing command 'ruff'. Attempting system package installation.")
    try:
        detect_package_manager()
        try:
            install_command_via_pkg("ruff")
        except RuntimeError as exc:
            log(f"System package install failed for 'ruff': {exc}")
    except RuntimeError:
        log("No supported package manager found; falling back to pip.")

    if which("ruff"):
        return

    log("Falling back to pip installation for 'ruff'.")
    spec = os.environ.get("RUFF_PIP_SPEC", "ruff")
    install_pip_pkg(spec)

    if not which("ruff"):
        raise RuntimeError("Command 'ruff' is still unavailable after installation.")
