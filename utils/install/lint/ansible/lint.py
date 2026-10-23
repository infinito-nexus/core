"""Install ansible-lint via pip."""

from __future__ import annotations

import os

from utils.install.pip import install_pip_pkg
from utils.install.primitives import log, which


def ensure() -> None:
    if which("ansible-lint"):
        return
    log("Missing command 'ansible-lint'. Installing via pip.")
    # nocheck: environ-get-default  the fallback is the package name this installer exists for; ANSIBLE_LINT_PIP_SPEC is the contributor's way to pin a version or a fork, and no deploy sets it
    spec = os.environ.get("ANSIBLE_LINT_PIP_SPEC", "ansible-lint")
    install_pip_pkg(spec)
    if not which("ansible-lint"):
        raise RuntimeError(
            "Command 'ansible-lint' is still unavailable after installation."
        )
