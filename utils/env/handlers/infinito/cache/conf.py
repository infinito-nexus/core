"""INFINITO_CACHE_PACKAGE_FRONTEND_CONF: nginx upstream map the shared
package-cache frontend mounts, taken from the primary checkout unless
INFINITO_CACHE_CONF_SOURCE says worktree."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_PACKAGE_FRONTEND_CONF"
SOURCE_KEY = "INFINITO_CACHE_CONF_SOURCE"
COMMENT = (
    "Bind source for the package-cache frontend's nginx upstream map. "
    "One cache stack serves every checkout on the host, so it follows the "
    f"primary one; set {SOURCE_KEY}=worktree to test a change before merging."
)
RELATIVE = Path("compose") / "package-cache-frontend" / "upstreams.conf"


def primary_checkout(repo_root: Path) -> Path:
    """Return the checkout that owns the repository, given any worktree.

    Args:
        repo_root: the checkout this build runs in.

    Returns:
        The primary checkout's path, or ``repo_root`` when git cannot say.
    """
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        return repo_root
    if not common:
        return repo_root
    return Path(common).parent


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    source = (
        (os.environ.get(SOURCE_KEY) or ctx.static.get(SOURCE_KEY) or "").strip().lower()
    )
    root = ctx.repo_root if source == "worktree" else primary_checkout(ctx.repo_root)
    eb.setdefault(KEY, str(root / RELATIVE), comment=COMMENT)
