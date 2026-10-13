"""Install mbake via pip."""

from __future__ import annotations

import os

from utils.install.pip import install_pip_pkg
from utils.install.primitives import log, which


def ensure() -> None:
    if which("mbake"):
        return
    log("Missing command 'mbake'. Installing via pip.")
    # nocheck: environ-get-default  the fallback is the package name this installer exists for; MBAKE_PIP_SPEC is the contributor's way to pin a version or a fork, and no deploy sets it
    spec = os.environ.get("MBAKE_PIP_SPEC", "mbake")
    install_pip_pkg(spec)
    if not which("mbake"):
        raise RuntimeError("Command 'mbake' is still unavailable after installation.")
