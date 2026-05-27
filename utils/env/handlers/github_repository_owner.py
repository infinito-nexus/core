"""GITHUB_REPOSITORY_OWNER: lowercased GHA repository owner, derived
from GITHUB_REPOSITORY_OWNER / OWNER / GITHUB_REPOSITORY. Fatal if
unresolvable on GHA."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "GITHUB_REPOSITORY_OWNER"
COMMENT = "Lowercased GHA repository owner used to compose INFINITO_IMAGE."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    if not ctx.on_gha:
        return
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or os.environ.get("OWNER") or ""
    if not owner:
        repo_full = os.environ.get("GITHUB_REPOSITORY", "")
        if "/" in repo_full:
            owner = repo_full.split("/", 1)[0]
    owner = owner.lower()
    if not owner:
        print(
            "ERROR: GITHUB_REPOSITORY_OWNER (or GITHUB_REPOSITORY/OWNER) must "
            "be set when GITHUB_ACTIONS=true",
            file=sys.stderr,
        )
        sys.exit(2)
    eb.set(KEY, owner, comment=COMMENT)
