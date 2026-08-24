"""Install stylelint (locally in repo root via npm; parser for lint-css).

Provisioning is best effort: a host that cannot reach the npm registry must not
fail the whole gate. scripts/lint/css.sh skips loudly instead.
"""

from __future__ import annotations

from pathlib import Path

from utils.cache import PROJECT_ROOT
from utils.install.npm import npm_install_local_in_repo
from utils.install.primitives import log, warn


def ensure() -> None:
    repo_root = Path(PROJECT_ROOT)
    if (repo_root / "node_modules" / "stylelint").is_dir():
        return

    log("Missing local 'stylelint'. Installing via npm (in repo root).")
    try:
        npm_install_local_in_repo(str(repo_root))
    except (RuntimeError, OSError) as exc:
        warn(f"[install-lint] stylelint could not be installed: {exc}")

    if not (repo_root / "node_modules" / "stylelint").is_dir():
        warn("[install-lint] stylelint is unavailable; lint-css will skip.")
