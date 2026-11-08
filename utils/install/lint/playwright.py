"""Install @playwright/test (locally in repo root via npm)."""

from __future__ import annotations

from pathlib import Path

from utils.cache import PROJECT_ROOT
from utils.install.npm import npm_install_local_in_repo, npm_local_missing
from utils.install.primitives import log


def ensure() -> None:
    repo_root = Path(PROJECT_ROOT)
    missing = npm_local_missing(str(repo_root))
    if not missing:
        return

    log(f"Missing local {', '.join(missing)}. Installing via npm (in repo root).")
    npm_install_local_in_repo(str(repo_root))

    still_missing = npm_local_missing(str(repo_root))
    if still_missing:
        raise RuntimeError(
            f"Local {', '.join(still_missing)} still unavailable after installation."
        )
