"""Install sqlfluff via pip (parser for lint-sql).

Provisioning is best effort: a host that cannot reach PyPI must not fail the
whole gate. scripts/lint/sql.sh skips loudly instead.
"""

from __future__ import annotations

from utils.install.pip import install_pip_pkg
from utils.install.primitives import log, warn, which


def ensure() -> None:
    if which("sqlfluff"):
        return

    log("Missing command 'sqlfluff'. Installing via pip.")
    try:
        install_pip_pkg("sqlfluff")
    except (RuntimeError, OSError) as exc:
        warn(f"[install-lint] sqlfluff could not be installed: {exc}")

    if not which("sqlfluff"):
        warn("[install-lint] sqlfluff is unavailable; lint-sql will skip.")
