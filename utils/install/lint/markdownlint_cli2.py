"""Install markdownlint-cli2 via npm global."""

from __future__ import annotations

from utils.install.npm import npm_install_global
from utils.install.primitives import log, which


def ensure() -> None:
    if which("markdownlint-cli2"):
        return
    log("Missing command 'markdownlint-cli2'. Installing via npm.")
    npm_install_global("markdownlint-cli2")
    if not which("markdownlint-cli2"):
        raise RuntimeError(
            "Command 'markdownlint-cli2' is still unavailable after installation."
        )
