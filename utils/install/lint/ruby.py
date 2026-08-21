"""Install the Ruby CLI via system package manager (parser for lint-ruby).

Provisioning is best effort: a host without Ruby, or one that cannot install it,
must not fail the whole gate. scripts/lint/ruby.sh skips loudly instead.
"""

from __future__ import annotations

from utils.install.primitives import log, warn, which
from utils.install.system_pkg import install_command_via_pkg


def ensure() -> None:
    if which("ruby"):
        return

    log("Missing command 'ruby'. Attempting system package installation.")
    try:
        install_command_via_pkg("ruby")
    except RuntimeError as exc:
        warn(f"[install-lint] ruby could not be installed: {exc}")

    if not which("ruby"):
        warn("[install-lint] ruby is unavailable; lint-ruby will skip.")
