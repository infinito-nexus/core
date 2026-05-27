"""Install @playwright/test (locally in repo root via npm)."""

from __future__ import annotations

from pathlib import Path

from utils.cache import PROJECT_ROOT
from utils.install.npm import npm_install_local_in_repo
from utils.install.primitives import log


def ensure() -> None:
    repo_root = Path(PROJECT_ROOT)
    if (repo_root / "node_modules" / "@playwright" / "test").is_dir():
        return

    log("Missing local '@playwright/test'. Installing via npm (in repo root).")
    npm_install_local_in_repo(str(repo_root))

    if not (repo_root / "node_modules" / "@playwright" / "test").is_dir():
        raise RuntimeError(
            "Local '@playwright/test' is still unavailable after installation."
        )
