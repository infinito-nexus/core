"""Install the PHP CLI via system package manager (parser for lint-php).

Provisioning is best effort: a host without PHP, or one that cannot install it,
must not fail the whole gate. scripts/lint/php.sh skips loudly instead.
"""

from __future__ import annotations

from utils.install.primitives import log, warn, which
from utils.install.system_pkg import install_command_via_pkg


def ensure() -> None:
    if which("php"):
        return

    log("Missing command 'php'. Attempting system package installation.")
    try:
        install_command_via_pkg("php")
    except RuntimeError as exc:
        warn(f"[install-lint] php could not be installed: {exc}")

    if not which("php"):
        warn("[install-lint] php is unavailable; lint-php will skip.")
