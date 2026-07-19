"""INFINITO_IMAGE_REPOSITORY: lowercased repository name resolved from
scripts/meta/resolve/repository/name.sh (GHA-only)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from utils.env.runtime import run_helper

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_IMAGE_REPOSITORY"
COMMENT = (
    "Lowercased repository name resolved from scripts/meta/resolve/repository/name.sh."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    if not ctx.on_gha:
        return
    repo_name = os.environ.get(
        "INFINITO_IMAGE_REPOSITORY", ""
    ).strip()  # nocheck: handler-bootstrap-read
    if not repo_name:
        repo_name = run_helper(
            ["bash", "scripts/meta/resolve/repository/name.sh"],
            cwd=ctx.repo_root,
        )
    repo_name = repo_name.lower()
    eb.set(KEY, repo_name, comment=COMMENT)
